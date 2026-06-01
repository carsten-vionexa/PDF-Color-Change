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


def load_colour_mapping(config_path: Path) -> list[dict[str, str]]:
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


def count_colour_matches(
    image_bytes: bytes,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> tuple[dict[str, int], dict[str, Any]]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        pixels = rgb_image.getdata()

        match_counts: dict[str, int] = defaultdict(int)
        for pixel in pixels:
            for mapping in colour_mapping:
                if rgb_distance(pixel, mapping["from_rgb"]) <= tolerance:
                    match_counts[mapping["label"]] += 1

        metadata = {
            "width": width,
            "height": height,
            "mode": image.mode,
            "format": image.format,
            "pixel_count": width * height,
        }

    return dict(match_counts), metadata


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
            match_counts, image_metadata = count_colour_matches(
                image_bytes=image_bytes,
                colour_mapping=colour_mapping,
                tolerance=tolerance,
            )
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


def run(input_dir: Path, output_dir: Path, config_path: Path, analyze: bool, tolerance: int) -> int:
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
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE, help="RGB distance tolerance for colour matching.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(args.input_dir, args.output_dir, args.config, args.analyze, args.tolerance)


if __name__ == "__main__":
    raise SystemExit(main())
