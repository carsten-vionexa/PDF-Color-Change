# PDF Color Change

Python project for automated colour replacement in DiSG PDF reports.

## Current status

The current working approach is the **preserve-text workflow**:

- PDF text, fonts and page structure are kept searchable where possible.
- Vector colour areas are replaced directly in PDF content streams.
- Embedded PNG diagram images are recoloured and replaced as image objects.
- Original input PDFs remain unchanged.
- New PDFs and JSON logs are written to `output/`.

This workflow was validated with the Sophie test PDF. The successful settings were:

```bash
python scripts/replace_pdf_preserve_text.py \
  --vector-tolerance 30 \
  --image-tolerance 45 \
  --image-operation replace \
  --image-overlay-mode full \
  --min-image-dimension 50
```

These are now also the relevant defaults in `scripts/replace_pdf_preserve_text.py`.

## Project structure

```text
.
├── config/
│   └── farbtabelle.json
├── input/
│   └── .gitkeep
├── output/
│   └── .gitkeep
├── scripts/
│   ├── analyze_pdf_vectors.py
│   ├── recolor_disc_pdfs.py
│   └── replace_pdf_preserve_text.py
├── .gitignore
├── README.md
└── requirements.txt
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Recommended usage

Place one or more PDFs in `input/` and run:

```bash
source .venv/bin/activate
python scripts/replace_pdf_preserve_text.py
```

The output files are written as:

```text
output/<original-name>_preserve_text.pdf
output/<original-name>_preserve_text_log.json
```

## Colour mapping

The replacement table is stored in `config/farbtabelle.json`.

Current mapping:

| Label | From | To |
|---|---:|---:|
| D hell | `#c3e3ca` | `#fccdc0` |
| D kraeftig | `#8acc9c` | `#f79f8e` |
| i hell | `#fccdc0` | `#ffe6b0` |
| i kraeftig | `#f79f8e` | `#ffd167` |
| G hell | `#ffe6b0` | `#b6d9ee` |
| G kraeftig | `#ffd167` | `#6dbce3` |
| S hell | `#b6d9ee` | `#c3e3ca` |
| S kraeftig | `#6dbce3` | `#8acc9c` |

## Important scripts

### `scripts/replace_pdf_preserve_text.py`

Main production candidate.

It performs two operations:

1. **Vector replacement**
   - Scans PDF content streams for RGB fill/stroke colour operators such as `rg` and `RG`.
   - Replaces matching DiSG colours with the configured target colours.
   - This is important for pages such as the DiSG overview page where the large coloured areas are vector shapes behind searchable text.

2. **Image object replacement**
   - Scans embedded PNG images on the configured image pages.
   - Recolours image pixels using tolerance-based matching.
   - Replaces the original image object instead of adding an overlay.
   - This avoids duplicate colours and preserves markers such as black dots, arrows, lines and labels inside the small diagrams.

Useful options:

```bash
python scripts/replace_pdf_preserve_text.py --vector-tolerance 30
python scripts/replace_pdf_preserve_text.py --image-tolerance 45
python scripts/replace_pdf_preserve_text.py --image-pages 8-15
python scripts/replace_pdf_preserve_text.py --image-operation replace
python scripts/replace_pdf_preserve_text.py --image-overlay-mode full
python scripts/replace_pdf_preserve_text.py --min-image-dimension 50
```

Recommended command:

```bash
python scripts/replace_pdf_preserve_text.py \
  --vector-tolerance 30 \
  --image-tolerance 45 \
  --image-pages 8-15 \
  --image-operation replace \
  --image-overlay-mode full \
  --min-image-dimension 50
```

### `scripts/analyze_pdf_vectors.py`

Diagnostic script for checking vector colours in PDF content streams.

```bash
python scripts/analyze_pdf_vectors.py
```

Creates:

```text
output/<original-name>_vector_analysis_log.json
```

Use this when a new PDF layout does not recolour correctly and you need to inspect which vector colours are present.

### `scripts/recolor_disc_pdfs.py`

Earlier prototype script.

It supports image analysis and rendered-page fallback modes. The rendered-page mode is visually robust but turns pages into images, so it is not the preferred final workflow when PDF text searchability must be preserved.

## QA checklist

After each run, check:

1. Output PDF exists in `output/`.
2. JSON log exists in `output/`.
3. Pages 1-7: vector-colour areas are correct.
4. Pages 8-15: small diagrams have correct colours.
5. Pages 8-15: black dots, arrows, contour lines and labels are still visible.
6. Text search still works in the output PDF for normal body text.
7. Original PDFs in `input/` are unchanged.

## Notes from the Sophie test

The final successful mode was:

```text
mode: preserve-text-vector-plus-image-object-replacement
vector_tolerance: 30
image_tolerance: 45
image_pages: 8-15
image_overlay_mode: full
image_operation: replace
min_image_dimension: 50
```

The log showed vector replacements on pages 2-7 and 16-20, and PNG image-object replacements on pages 8-15.

## Known limitations / next steps

- The current vector parser handles common RGB operators `rg` and `RG`.
- Future PDFs may use other colour operators or colour spaces, such as `sc`, `scn`, `k`, `K`, ICCBased or patterns.
- If a new PDF does not recolour correctly, first run `scripts/analyze_pdf_vectors.py` and inspect the JSON log.
- If embedded image replacement does not work on another PDF variant, compare the generated preserve-text log and inspect image XRefs, page ranges and image dimensions.
