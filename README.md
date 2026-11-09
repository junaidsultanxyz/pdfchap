# pdfchap

`pdfchap` is a cross-platform, programmatic command-line interface (CLI) tool and Python library designed to parse a PDF's table of contents (bookmarks) and extract specified chapters or sections into clean, standalone PDF files while preserving nested sub-bookmarks.

It is natively built to be fully compatible with automated AI agents, CI/CD pipelines, and scripting environments (supporting zero-interaction flags and deterministic file outputs).

---

## Installation & Setup

### Requirements

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or standard `pip`

### Installing with `uv` (Recommended)

From the project root directory:

```bash
# Install dependencies and sync virtual environment
uv sync

# Install globally on your system as an editable command-line tool
uv tool install --editable .
```

---

## Agent Usage Guide (CLI Commands)

When an AI agent executes shell commands, it **must** run in non-interactive mode using automation flags (`--all` or `--match`) to prevent the CLI from hanging on interactive menu prompts.

### 1. Smart Chapter Extraction (`--chapters`)

Automatically filters out giant wrapper sections (like "Part One") and extracts only clean, top-level chapters and appendices. It also includes auto-recovery logic for PDFs where chapter bookmarks are hidden inside Part pages.

```bash
pdfchap "book.pdf" --chapters --all -o ./extracted_chapters
```

### 2. Regex / Substring Targeting (`--match`)

Allows an agent to isolate and extract a specific chapter without reviewing a menu:

```bash
pdfchap "book.pdf" --chapters --match "Chapter 2\b" -o ./output
```

### 3. Hierarchy Depth Filtering (`-l / --level`)

Limits the maximum bookmark tree depth displayed or processed (e.g., Level 1 for top-level entries only):

```bash
pdfchap "book.pdf" --level 1 --all -o ./top_level_sections
```

---

## Python API Usage for AI Agents

Because `pdfchap` is packaged as a standard Python library (`src/pdfchap/`), a Python-based agent can import and call its core functions directly without invoking subprocesses.

```python
import fitz
from pathlib import Path
from pdfchap.cli import parse_chapters, extract_chapter

# 1. Open the PDF document
pdf_path = Path("book.pdf")
doc = fitz.open(pdf_path)

# 2. Extract TOC and parse chapter boundaries (smart chapter mode enabled)
full_toc = doc.get_toc()
chapters = parse_chapters(doc, smart_chapters=True)

# 3. Filter or select target chapters programmatically
target = next((c for c in chapters if "Cryptographic" in c["title"]), None)

if target:
    out_dir = Path("./extracted_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 4. Extract chapter and preserve nested sub-bookmarks (e.g., 2.1, 2.2)
    saved_file = extract_chapter(doc, target, full_toc, out_dir)
    print(f"Successfully extracted: {saved_file}")

doc.close()
```

---

## Design Features for AI Workflows

- **Deterministic File Naming:** Automatically sanitizes chapter titles (removing slashes, colons, and illegal path characters) to ensure safe, predictable file paths (e.g., `CHAPTER 2 - CRYPTOGRAPHIC TOOLS.pdf`).
- **Sub-Bookmark Retention:** Extracted chapter PDFs retain their internal nested sub-sections shifted to start at page 1, making them immediately ready for downstream RAG (Retrieval-Augmented Generation) pipelines or document summarization agents.
- **Exit Codes:** Returns standard POSIX exit codes (`0` on success, non-zero on missing files or invalid parameters) for robust error-handling by supervisor agents.
