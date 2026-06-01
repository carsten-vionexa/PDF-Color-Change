from __future__ import annotations

import argparse
import io
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "farbtabelle.json"
DEFAULT_VECTOR_TOLERANCE = 30
DEFAULT_IMAGE_TOLERANCE = 45
DEFAULT_IMAGE_PAGE_RANGE = "8-15"
DEFAULT_IMAGE_OVERLAY_MODE = "full"
DEFAULT_MIN_IMAGE_DIMENSION = 50

RGB_OPERATOR_RE = re.compile(
    rb"(?P<r>[+-]?(?:\d+\.\d+|\.\d+|\d+))\s+"
    rb"(?P<g>[+-]?(?:\d+\.\d+|\.\d+|\d+))\s+"
    rb"(?P<b>[+-]?(?:\d+\.\d+|\.\d+|\d+))\s+"
    rb"(?P<op>rg|RG)\b"
)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex colour: {value}")
    return tuple(int(cleaned[index : index + 2], 16) for index in (0, 2, 4))


def load_colour_mapping(config_path: Path) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    for item in data:
        item["from_rgb"] = hex_to_rgb(item["from"])
        item["to_rgb"] = hex_to_rgb(item["to"])
    return data


def rgb_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def nearest_mapping(
    pixel: tuple[int, int, int],
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> dict[str, Any] | None:
    best_mapping = None
    best_distance = None
    for mapping in colour_mapping:
        distance = rgb_distance(pixel, mapping["from_rgb"])
        if distance <= tolerance and (best_distance is None or distance < best_distance):
            best_mapping = mapping
            best_distance = distance
    return best_mapping


def pdf_rgb_to_255(*values: bytes) -> tuple[int, int, int]:
    result = []
    for value in values:
        numeric = float(value.decode("ascii"))
        numeric = max(0.0, min(1.0, numeric))
        result.append(round(numeric * 255))
    return tuple(result)


def rgb_to_pdf_operands(rgb: tuple[int, int, int], operator: bytes) -> bytes:
    return (
        f"{rgb[0] / 255:.6f} {rgb[1] / 255:.6f} {rgb[2] / 255:.6f} "
    ).encode("ascii") + operator


def recolour_content_stream(
    content: bytes,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> tuple[bytes, dict[str, int]]:
    replacement_counts: dict[str, int] = defaultdict(int)

    def replace_match(match: re.Match[bytes]) -> bytes:
        source_rgb = pdf_rgb_to_255(match.group("r"), match.group("g"), match.group("b"))
        mapping = nearest_mapping(source_rgb, colour_mapping, tolerance)
        if mapping is None:
            return match.group(0)

        operator = match.group("op")
        replacement_counts[f"{mapping['label']} ({operator.decode('ascii')})"] += 1
        return rgb_to_pdf_operands(mapping["to_rgb"], operator)

    return RGB_OPERATOR_RE.sub(replace_match, content), dict(replacement_counts)


def recolour_image_pixels(
    image: Image.Image,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
    overlay_mode: str,
) -> tuple[bytes, dict[str, int], dict[str, Any]]:
    rgba_image = image.convert("RGBA")
    width, height = rgba_image.size
    source = rgba_image.tobytes()
    output_pixels = bytearray(len(source))
    replacement_counts: dict[str, int] = defaultdict(int)

    for index in range(0, len(source), 4):
        alpha = source[index + 3]
        source_rgb = (source[index], source[index + 1], source[index + 2])
        mapping = nearest_mapping(source_rgb, colour_mapping, tolerance) if alpha else None

        if overlay_mode == "matched":
            if mapping is None:
                output_pixels[index + 3] = 0
                continue
            replacement = mapping["to_rgb"]
            output_pixels[index] = replacement[0]
            output_pixels[index + 1] = replacement[1]
            output_pixels[index + 2] = replacement[2]
            output_pixels[index + 3] = 255
            replacement_counts[mapping["label"]] += 1
            continue

        if overlay_mode == "full":
            if mapping is None:
                output_pixels[index] = source[index]
                output_pixels[index + 1] = source[index + 1]
                output_pixels[index + 2] = source[index + 2]
                output_pixels[index + 3] = 255 if alpha else 0
            else:
                replacement = mapping["to_rgb"]
                output_pixels[index] = replacement[0]
                output_pixels[index + 1] = replacement[1]
                output_pixels[index + 2] = replacement[2]
                output_pixels[index + 3] = 255
                replacement_counts[mapping["label"]] += 1
            continue

        raise ValueError(f"Unsupported image overlay mode: {overlay_mode}")

    overlay_image = Image.frombytes("RGBA", (width, height), bytes(output_pixels))
    output = io.BytesIO()
    overlay_image.save(output, format="PNG")

    return output.getvalue(), dict(replacement_counts), {
        "width": width,
        "height": height,
        "pixel_count": width * height,
    }


def parse_page_range(value: str | None) -> set[int] | None:
    if value is None or value.strip().lower() in {"", "all"}:
        return None

    pages: set[int] = set()
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            pages.update(range(start, end + 1))
        else:
            pages.add(int(item))
    return pages


def find_pdf_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.pdf"))


def output_pdf_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_preserve_text.pdf"


def output_log_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_preserve_text_log.json"


def replace_vectors(document: fitz.Document, colour_mapping: list[dict[str, Any]], tolerance: int) -> list[dict[str, Any]]:
    page_results: list[dict[str, Any]] = []

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        content_xrefs = page.get_contents()
        page_counts: dict[str, int] = defaultdict(int)
        changed_streams = 0

        for xref in content_xrefs:
            content = document.xref_stream(xref) or b""
            new_content, counts = recolour_content_stream(content, colour_mapping, tolerance)
            if counts and new_content != content:
                document.update_stream(xref, new_content)
                changed_streams += 1
                for label, count in counts.items():
                    page_counts[label] += count

        page_result = {
            "page_number": page_index + 1,
            "content_stream_count": len(content_xrefs),
            "changed_streams": changed_streams,
            "vector_replacements": dict(page_counts),
        }
        page_results.append(page_result)

        if page_counts:
            summary = ", ".join(f"{label}: {count}" for label, count in sorted(page_counts.items()))
        else:
            summary = "no vector replacements"
        print(f"Page {page_index + 1} vectors: {summary}")

    return page_results


def overlay_recoloured_images(
    document: fitz.Document,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
    image_pages: set[int] | None,
    overlay_mode: str,
    min_image_dimension: int,
) -> list[dict[str, Any]]:
    image_results: list[dict[str, Any]] = []
    processed: set[tuple[int, int]] = set()

    for page_index in range(document.page_count):
        page_number = page_index + 1
        if image_pages is not None and page_number not in image_pages:
            continue

        page = document.load_page(page_index)
        for image_info in page.get_images(full=True):
            xref = image_info[0]
            key = (page_number, xref)
            if key in processed:
                continue
            processed.add(key)

            extracted = document.extract_image(xref)
            extension = str(extracted.get("ext", "")).lower()
            if extension != "png":
                continue

            with Image.open(io.BytesIO(extracted["image"])) as image:
                if min(image.size) < min_image_dimension:
                    continue
                overlay_bytes, counts, metadata = recolour_image_pixels(
                    image=image,
                    colour_mapping=colour_mapping,
                    tolerance=tolerance,
                    overlay_mode=overlay_mode,
                )

            if not counts:
                continue

            rects = page.get_image_rects(xref)
            if not rects:
                continue

            for rect in rects:
                page.insert_image(rect, stream=overlay_bytes, overlay=True)

            image_result = {
                "page_number": page_number,
                "xref": xref,
                "extension": extension,
                "rect_count": len(rects),
                "overlay_mode": overlay_mode,
                "image_replacements": counts,
                **metadata,
            }
            image_results.append(image_result)
            summary = ", ".join(f"{label}: {count}" for label, count in sorted(counts.items()))
            print(f"Page {page_number} image xref {xref}: {summary}")

    return image_results


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    colour_mapping: list[dict[str, Any]],
    vector_tolerance: int,
    image_tolerance: int,
    image_pages: set[int] | None,
    image_overlay_mode: str,
    min_image_dimension: int,
) -> dict[str, Any]:
    document = fitz.open(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_pdf_path(pdf_path, output_dir)

    print(f"PDF: {pdf_path}")
    vector_results = replace_vectors(document, colour_mapping, vector_tolerance)
    image_results = overlay_recoloured_images(
        document=document,
        colour_mapping=colour_mapping,
        tolerance=image_tolerance,
        image_pages=image_pages,
        overlay_mode=image_overlay_mode,
        min_image_dimension=min_image_dimension,
    )

    document.save(output_path, garbage=4, deflate=True)
    document.close()

    result = {
        "pdf": str(pdf_path),
        "output_pdf": str(output_path),
        "mode": "preserve-text-vector-plus-image-overlay",
        "vector_tolerance": vector_tolerance,
        "image_tolerance": image_tolerance,
        "image_pages": "all" if image_pages is None else sorted(image_pages),
        "image_overlay_mode": image_overlay_mode,
        "min_image_dimension": min_image_dimension,
        "vector_pages": vector_results,
        "image_overlays": image_results,
    }

    log_path = output_log_path(pdf_path, output_dir)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(f"Output PDF: {output_path}")
    print(f"Log: {log_path}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replace PDF colours while preserving searchable text.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--vector-tolerance", type=int, default=DEFAULT_VECTOR_TOLERANCE)
    parser.add_argument("--image-tolerance", type=int, default=DEFAULT_IMAGE_TOLERANCE)
    parser.add_argument("--image-pages", default=DEFAULT_IMAGE_PAGE_RANGE)
    parser.add_argument(
        "--image-overlay-mode",
        choices=("full", "matched"),
        default=DEFAULT_IMAGE_OVERLAY_MODE,
    )
    parser.add_argument("--min-image-dimension", type=int, default=DEFAULT_MIN_IMAGE_DIMENSION)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    colour_mapping = load_colour_mapping(args.config)
    image_pages = parse_page_range(args.image_pages)
    pdf_files = find_pdf_files(args.input_dir)

    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}")
        return 0

    for pdf_path in pdf_files:
        process_pdf(
            pdf_path=pdf_path,
            output_dir=args.output_dir,
            colour_mapping=colour_mapping,
            vector_tolerance=args.vector_tolerance,
            image_tolerance=args.image_tolerance,
            image_pages=image_pages,
            image_overlay_mode=args.image_overlay_mode,
            min_image_dimension=args.min_image_dimension,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
