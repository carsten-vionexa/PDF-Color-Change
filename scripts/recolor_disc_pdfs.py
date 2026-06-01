from __future__ import annotations

import argparse
import io
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "farbtabelle.json"
DEFAULT_TOLERANCE = 18
DEFAULT_REPLACE_FORMATS = {"png"}
DEFAULT_RENDER_DPI = 180


def load_colour_mapping(config_path: Path) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Colour mapping must be a JSON list.")

    required_keys = {"label", "from", "to"}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each colour mapping entry must be an object.")
        missing_keys = required_keys.difference(item)
        if missing_keys:
            raise ValueError(f"Colour mapping entry is missing keys: {sorted(missing_keys)}")
        item["from_rgb"] = hex_to_rgb(item["from"])
        item["to_rgb"] = hex_to_rgb(item["to"])

    return data


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex colour: {value}")
    return tuple(int(cleaned[index : index + 2], 16) for index in (0, 2, 4))


def rgb_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def find_pdf_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.pdf"))


def planned_output_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_recolored.pdf"


def analysis_log_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_analysis_log.json"


def replacement_log_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_replacement_log.json"


def nearest_mapping(
    pixel: tuple[int, int, int],
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> dict[str, Any] | None:
    best_mapping: dict[str, Any] | None = None
    best_distance: float | None = None

    for mapping in colour_mapping:
        distance = rgb_distance(pixel, mapping["from_rgb"])
        if distance <= tolerance and (best_distance is None or distance < best_distance):
            best_mapping = mapping
            best_distance = distance

    return best_mapping


def count_colour_matches(
    image_bytes: bytes,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> tuple[dict[str, int], dict[str, Any]]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        raw = rgb_image.tobytes()

        match_counts: dict[str, int] = defaultdict(int)
        for index in range(0, len(raw), 3):
            pixel = (raw[index], raw[index + 1], raw[index + 2])
            mapping = nearest_mapping(pixel, colour_mapping, tolerance)
            if mapping is not None:
                match_counts[mapping["label"]] += 1

        metadata = {
            "width": width,
            "height": height,
            "mode": image.mode,
            "format": image.format,
            "pixel_count": width * height,
        }

    return dict(match_counts), metadata


def recolour_pil_image(
    image: Image.Image,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> tuple[Image.Image, dict[str, int]]:
    rgba_image = image.convert("RGBA")
    width, height = rgba_image.size
    raw = bytearray(rgba_image.tobytes())
    replacement_counts: dict[str, int] = defaultdict(int)

    for index in range(0, len(raw), 4):
        alpha = raw[index + 3]
        if alpha == 0:
            continue

        pixel = (raw[index], raw[index + 1], raw[index + 2])
        mapping = nearest_mapping(pixel, colour_mapping, tolerance)
        if mapping is None:
            continue

        replacement = mapping["to_rgb"]
        raw[index] = replacement[0]
        raw[index + 1] = replacement[1]
        raw[index + 2] = replacement[2]
        replacement_counts[mapping["label"]] += 1

    return Image.frombytes("RGBA", (width, height), bytes(raw)), dict(replacement_counts)


def recolour_image(
    image_bytes: bytes,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> tuple[bytes, dict[str, int], dict[str, Any]]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
        recoloured, replacement_counts = recolour_pil_image(image, colour_mapping, tolerance)
        output = io.BytesIO()
        recoloured.save(output, format="PNG")

        metadata = {
            "width": width,
            "height": height,
            "mode": image.mode,
            "format": image.format,
            "pixel_count": width * height,
        }

    return output.getvalue(), replacement_counts, metadata


def analyse_pdf(
    pdf_path: Path,
    output_dir: Path,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> dict[str, Any]:
    document = fitz.open(pdf_path)
    result: dict[str, Any] = {
        "pdf": str(pdf_path),
        "page_count": document.page_count,
        "tolerance": tolerance,
        "pages": [],
    }

    print(f"PDF: {pdf_path}")
    print(f"Pages: {document.page_count}")

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        images = page.get_images(full=True)
        page_result: dict[str, Any] = {
            "page_number": page_index + 1,
            "image_count": len(images),
            "images": [],
        }

        print(f"Page {page_index + 1}: {len(images)} image(s) found")

        for image_index, image_info in enumerate(images, start=1):
            xref = image_info[0]
            extracted = document.extract_image(xref)
            image_bytes = extracted["image"]
            match_counts, image_metadata = count_colour_matches(image_bytes, colour_mapping, tolerance)
            image_result = {
                "image_number": image_index,
                "xref": xref,
                "extension": extracted.get("ext"),
                **image_metadata,
                "matches": match_counts,
            }
            page_result["images"].append(image_result)

            if match_counts:
                match_summary = ", ".join(
                    f"{label}: {count}" for label, count in sorted(match_counts.items())
                )
            else:
                match_summary = "no colour matches"

            print(
                f"  Image {image_index}: "
                f"{image_metadata['width']}x{image_metadata['height']}, "
                f"{match_summary}"
            )

        result["pages"].append(page_result)

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = analysis_log_path(pdf_path, output_dir)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(f"Analysis log: {log_path}")
    document.close()
    return result


def replace_pdf_image_objects(
    pdf_path: Path,
    output_dir: Path,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
    replace_formats: set[str],
) -> dict[str, Any]:
    document = fitz.open(pdf_path)
    output_path = planned_output_path(pdf_path, output_dir)
    result: dict[str, Any] = {
        "pdf": str(pdf_path),
        "output_pdf": str(output_path),
        "mode": "image-objects",
        "page_count": document.page_count,
        "tolerance": tolerance,
        "replace_formats": sorted(replace_formats),
        "replaced_images": [],
        "skipped_images": [],
    }

    processed_xrefs: set[int] = set()
    pages_by_xref: dict[int, set[int]] = defaultdict(set)

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        for image_info in page.get_images(full=True):
            pages_by_xref[image_info[0]].add(page_index + 1)

    print(f"PDF: {pdf_path}")
    print(f"Pages: {document.page_count}")

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        images = page.get_images(full=True)

        for image_info in images:
            xref = image_info[0]
            if xref in processed_xrefs:
                continue
            processed_xrefs.add(xref)

            extracted = document.extract_image(xref)
            extension = str(extracted.get("ext", "")).lower()

            if extension not in replace_formats:
                result["skipped_images"].append(
                    {
                        "xref": xref,
                        "extension": extension,
                        "pages": sorted(pages_by_xref[xref]),
                        "reason": "format not selected for replacement",
                    }
                )
                continue

            image_bytes = extracted["image"]
            recoloured_bytes, replacement_counts, image_metadata = recolour_image(
                image_bytes, colour_mapping, tolerance
            )

            if not replacement_counts:
                result["skipped_images"].append(
                    {
                        "xref": xref,
                        "extension": extension,
                        "pages": sorted(pages_by_xref[xref]),
                        "reason": "no colour matches",
                        **image_metadata,
                    }
                )
                continue

            page.replace_image(xref, stream=recoloured_bytes)
            replaced_image = {
                "xref": xref,
                "extension": extension,
                "pages": sorted(pages_by_xref[xref]),
                **image_metadata,
                "replacements": replacement_counts,
            }
            result["replaced_images"].append(replaced_image)
            replacement_summary = ", ".join(
                f"{label}: {count}" for label, count in sorted(replacement_counts.items())
            )
            print(
                f"Replaced xref {xref} on page(s) {sorted(pages_by_xref[xref])}: "
                f"{replacement_summary}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    document.save(output_path, garbage=4, deflate=True)
    document.close()

    log_path = replacement_log_path(pdf_path, output_dir)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(f"Output PDF: {output_path}")
    print(f"Replacement log: {log_path}")
    return result


def render_page_to_image(page: fitz.Page, dpi: int) -> Image.Image:
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGBA")


def replace_pdf_rendered_pages(
    pdf_path: Path,
    output_dir: Path,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
    render_dpi: int,
) -> dict[str, Any]:
    source_document = fitz.open(pdf_path)
    output_document = fitz.open()
    output_path = planned_output_path(pdf_path, output_dir)
    result: dict[str, Any] = {
        "pdf": str(pdf_path),
        "output_pdf": str(output_path),
        "mode": "rendered-pages",
        "page_count": source_document.page_count,
        "tolerance": tolerance,
        "render_dpi": render_dpi,
        "pages": [],
    }

    print(f"PDF: {pdf_path}")
    print(f"Pages: {source_document.page_count}")
    print(f"Replacement mode: rendered-pages at {render_dpi} dpi")

    for page_index in range(source_document.page_count):
        source_page = source_document.load_page(page_index)
        rendered = render_page_to_image(source_page, render_dpi)
        recoloured, replacement_counts = recolour_pil_image(rendered, colour_mapping, tolerance)

        image_output = io.BytesIO()
        recoloured.convert("RGB").save(image_output, format="JPEG", quality=95)
        image_bytes = image_output.getvalue()

        page_rect = source_page.rect
        output_page = output_document.new_page(width=page_rect.width, height=page_rect.height)
        output_page.insert_image(page_rect, stream=image_bytes)

        page_result = {
            "page_number": page_index + 1,
            "width": rendered.width,
            "height": rendered.height,
            "pixel_count": rendered.width * rendered.height,
            "replacements": replacement_counts,
        }
        result["pages"].append(page_result)

        if replacement_counts:
            replacement_summary = ", ".join(
                f"{label}: {count}" for label, count in sorted(replacement_counts.items())
            )
        else:
            replacement_summary = "no colour matches"
        print(f"Page {page_index + 1}: {replacement_summary}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_document.save(output_path, garbage=4, deflate=True)
    output_document.close()
    source_document.close()

    log_path = replacement_log_path(pdf_path, output_dir)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(f"Output PDF: {output_path}")
    print(f"Replacement log: {log_path}")
    return result


def parse_replace_formats(value: str) -> set[str]:
    formats = {item.strip().lower().lstrip(".") for item in value.split(",") if item.strip()}
    if not formats:
        raise ValueError("At least one replacement image format must be provided.")
    return formats


def run(
    input_dir: Path,
    output_dir: Path,
    config_path: Path,
    analyze: bool,
    replace: bool,
    tolerance: int,
    replace_formats: set[str],
    replace_mode: str,
    render_dpi: int,
) -> int:
    colour_mapping = load_colour_mapping(config_path)
    pdf_files = find_pdf_files(input_dir)

    print(f"Loaded {len(colour_mapping)} colour mapping entries from {config_path}")

    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_files:
        if analyze:
            analyse_pdf(pdf_path, output_dir, colour_mapping, tolerance)
        elif replace:
            if replace_mode == "image-objects":
                replace_pdf_image_objects(pdf_path, output_dir, colour_mapping, tolerance, replace_formats)
            elif replace_mode == "rendered-pages":
                replace_pdf_rendered_pages(pdf_path, output_dir, colour_mapping, tolerance, render_dpi)
            else:
                raise ValueError(f"Unsupported replacement mode: {replace_mode}")
        else:
            print(f"Found PDF: {pdf_path}")
            print(f"Planned output: {planned_output_path(pdf_path, output_dir)}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recolour DiSG PDF graphics.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--analyze", action="store_true", help="Analyse embedded images and colour matches.")
    parser.add_argument("--replace", action="store_true", help="Replace colours and write recoloured PDFs.")
    parser.add_argument(
        "--replace-mode",
        choices=("rendered-pages", "image-objects"),
        default="rendered-pages",
        help="Replacement mode. Default: rendered-pages for reliable visual output.",
    )
    parser.add_argument(
        "--replace-formats",
        type=parse_replace_formats,
        default=DEFAULT_REPLACE_FORMATS,
        help="Comma-separated image formats for image-objects mode. Default: png",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=DEFAULT_RENDER_DPI,
        help="DPI for rendered-pages mode. Default: 180",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=DEFAULT_TOLERANCE,
        help="RGB distance tolerance for colour matching.",
    )
    args = parser.parse_args()

    if args.analyze and args.replace:
        parser.error("Use either --analyze or --replace, not both.")

    return args


def main() -> int:
    args = parse_args()
    return run(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        config_path=args.config,
        analyze=args.analyze,
        replace=args.replace,
        tolerance=args.tolerance,
        replace_formats=args.replace_formats,
        replace_mode=args.replace_mode,
        render_dpi=args.render_dpi,
    )


if __name__ == "__main__":
    raise SystemExit(main())
