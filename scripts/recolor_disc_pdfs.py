from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "farbtabelle.json"


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

    return data


def find_pdf_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.pdf"))


def planned_output_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_recolored.pdf"


def run(input_dir: Path, output_dir: Path, config_path: Path) -> int:
    colour_mapping = load_colour_mapping(config_path)
    pdf_files = find_pdf_files(input_dir)

    print(f"Loaded {len(colour_mapping)} colour mapping entries from {config_path}")

    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_files:
        print(f"Found PDF: {pdf_path}")
        print(f"Planned output: {planned_output_path(pdf_path, output_dir)}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recolour DiSG PDF graphics.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(args.input_dir, args.output_dir, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
