from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "farbtabelle.json"
DEFAULT_TOLERANCE = 18

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


def pdf_rgb_to_255(*values: bytes) -> tuple[int, int, int]:
    converted = []
    for value in values:
        numeric = float(value.decode("ascii"))
        numeric = max(0.0, min(1.0, numeric))
        converted.append(round(numeric * 255))
    return tuple(converted)


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


def find_pdf_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.pdf"))


def vector_log_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_vector_analysis_log.json"


def analyse_page_content(
    content: bytes,
    colour_mapping: list[dict[str, Any]],
    tolerance: int,
) -> dict[str, Any]:
    operator_counts: dict[str, int] = defaultdict(int)
    match_counts: dict[str, int] = defaultdict(int)
    raw_colours: dict[str, int] = defaultdict(int)

    for match in RGB_OPERATOR_RE.finditer(content):
        operator = match.group("op").decode("ascii")
        rgb = pdf_rgb_to_255(match.group("r"), match.group("g"), match.group("b"))
        raw_hex = "#" + "".join(f"{channel:02x}" for channel in rgb)
        operator_counts[operator] += 1
        raw_colours[raw_hex] += 1

        mapping = nearest_mapping(rgb, colour_mapping, tolerance)
        if mapping is not None:
            match_counts[f"{mapping['label']} ({operator})"] += 1

    return {
        "operator_counts": dict(operator_counts),
        "matches": dict(match_counts),
        "raw_colours": dict(sorted(raw_colours.items(), key=lambda item: (-item[1], item[0]))),
    }


def analyse_pdf(pdf_path: Path, output_dir: Path, colour_mapping: list[dict[str, Any]], tolerance: int) -> dict[str, Any]:
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
        content_xrefs = page.get_contents()
        combined_content = b""
        for xref in content_xrefs:
            combined_content += document.xref_stream(xref) or b""
            combined_content += b"\n"

        page_result = analyse_page_content(combined_content, colour_mapping, tolerance)
        page_result["page_number"] = page_index + 1
        page_result["content_stream_count"] = len(content_xrefs)
        result["pages"].append(page_result)

        if page_result["matches"]:
            match_summary = ", ".join(
                f"{label}: {count}" for label, count in sorted(page_result["matches"].items())
            )
        else:
            match_summary = "no vector colour matches"
        print(f"Page {page_index + 1}: {match_summary}")

    document.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = vector_log_path(pdf_path, output_dir)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
    print(f"Vector analysis log: {log_path}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyse PDF vector RGB colour operators.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    colour_mapping = load_colour_mapping(args.config)
    pdf_files = find_pdf_files(args.input_dir)
    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}")
        return 0

    for pdf_path in pdf_files:
        analyse_pdf(pdf_path, args.output_dir, colour_mapping, args.tolerance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
