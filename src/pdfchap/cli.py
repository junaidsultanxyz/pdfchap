from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF
import questionary

# Patterns to classify bookmarks even when the PDF has a broken/flat Level 1 outline
SUBSECTION_RE = re.compile(r"^\d+\.\d+\b")  # Matches "1.1", "2.1", "10.4", etc.
CHAPTER_RE = re.compile(r"^(chapter|appendix)\b", re.IGNORECASE)
PART_RE = re.compile(
    r"^part\s+(one|two|three|four|five|six|\d+|i+|v+)\b", re.IGNORECASE
)
BACKMATTER_RE = re.compile(
    r"^(acronyms|references|credits|index|glossary|bibliography)\b", re.IGNORECASE
)


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows, macOS, and Linux filenames."""
    cleaned = re.sub(r"[:/\\]+", " - ", name)
    cleaned = re.sub(r'[<>"|?*\x00-\x1f]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "Untitled_Chapter"


def detect_chapter_title_on_page(doc: fitz.Document, page_idx: int) -> str | None:
    """
    If a 'Part' bookmark shares its opening page with a 'Chapter' heading
    (and the PDF outline omitted the Chapter bookmark), scan the page text for 'CHAPTER X ...'
    """
    # Explicitly cast to str to satisfy static type checkers
    text = str(doc[page_idx].get_text("text"))
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        m = re.match(r"^CHAPTER\s+(\d+)\s*(.*)$", line, re.IGNORECASE)
        if m:
            chap_num = m.group(1)
            rest = m.group(2).strip()
            # If the title is on the next line, grab it
            if not rest and i + 1 < len(lines):
                rest = lines[i + 1]
            return f"CHAPTER {chap_num} {rest}".strip()

    return None


def is_major_boundary(title: str) -> bool:
    """True if a bookmark represents a top-level boundary (Chapter, Part, Appendix, Backmatter)."""
    if SUBSECTION_RE.match(title):
        return False
    return bool(
        CHAPTER_RE.match(title) or PART_RE.match(title) or BACKMATTER_RE.match(title)
    )


def parse_chapters(doc: fitz.Document, smart_chapters: bool = False) -> list[dict]:
    """
    Parse PDF bookmarks and calculate accurate 0-based start/end pages.
    If smart_chapters=True, handles flat outlines where 1.1 is at Level 1 and
    recovers chapters hidden under 'Part' bookmarks.
    """
    toc = doc.get_toc()
    if not toc:
        return []

    total_pages = len(doc)
    entries = []

    for i, (level, raw_title, start_page) in enumerate(toc):
        if start_page < 1 or start_page > total_pages:
            continue

        title = " ".join(raw_title.split())
        page_idx = start_page - 1

        # If a "Part" bookmark is immediately followed by a "X.1" subsection (like Part One -> 2.1),
        # check if the page actually starts a Chapter whose bookmark was omitted!
        recovered_chapter = None
        if smart_chapters and PART_RE.match(title) and i + 1 < len(toc):
            next_title = " ".join(toc[i + 1][1].split())
            if SUBSECTION_RE.match(next_title):
                detected = detect_chapter_title_on_page(doc, page_idx)
                if detected:
                    recovered_chapter = detected
                else:
                    chap_num = next_title.split(".")[0]
                    recovered_chapter = f"CHAPTER {chap_num} ({title})"

        entries.append(
            {
                "toc_index": i,
                "level": level,
                "title": recovered_chapter or title,
                "original_title": title,
                "is_recovered_chapter": bool(recovered_chapter),
                "start": page_idx,
            }
        )

    chapters = []
    for idx, item in enumerate(entries):
        start_idx = item["start"]
        end_idx = total_pages - 1

        if smart_chapters:
            # Only keep Chapters, Appendices, and recovered Part-Chapters
            is_chap = CHAPTER_RE.match(item["title"]) or item["is_recovered_chapter"]
            if not is_chap:
                continue

            # A chapter ends right before the next major boundary (Chapter, Part, Appendix, Backmatter)
            for next_item in entries[idx + 1 :]:
                if (
                    CHAPTER_RE.match(next_item["title"])
                    or next_item["is_recovered_chapter"]
                    or is_major_boundary(next_item["original_title"])
                ):
                    next_p = next_item["start"]
                    end_idx = (
                        max(start_idx, next_p - 1) if next_p > start_idx else start_idx
                    )
                    break
        else:
            # Standard hierarchy mode: ends before next bookmark of <= level
            for next_item in entries[idx + 1 :]:
                if next_item["level"] <= item["level"]:
                    next_p = next_item["start"]
                    end_idx = (
                        max(start_idx, next_p - 1) if next_p > start_idx else start_idx
                    )
                    break

        chapters.append(
            {
                "toc_index": item["toc_index"],
                "level": 1 if smart_chapters else item["level"],
                "title": item["title"],
                "start": start_idx,
                "end": end_idx,
            }
        )

    return chapters


def extract_chapter(
    doc: fitz.Document, chapter: dict, full_toc: list, out_dir: Path
) -> Path:
    """Extract page range into a new PDF and preserve nested sub-bookmarks."""
    new_doc = fitz.open()
    start_p, end_p = chapter["start"], chapter["end"]

    new_doc.insert_pdf(doc, from_page=start_p, to_page=end_p)

    # Include all bookmarks that fall within this chapter's page range
    sub_toc = []
    for idx, (lvl, raw_title, page) in enumerate(full_toc):
        if (start_p + 1) <= page <= (end_p + 1):
            clean_t = " ".join(raw_title.split())
            # Put the main chapter/part heading at level 1, and X.Y subsections at level 2
            sub_lvl = 2 if SUBSECTION_RE.match(clean_t) else 1
            sub_toc.append([sub_lvl, clean_t, page - start_p])

    if sub_toc:
        # Ensure first bookmark in TOC is level 1 (required by PyMuPDF)
        sub_toc[0][0] = 1
        new_doc.set_toc(sub_toc)

    safe_title = sanitize_filename(chapter["title"])
    out_path = out_dir / f"{safe_title}.pdf"

    counter = 1
    while out_path.exists():
        out_path = out_dir / f"{safe_title}_{counter}.pdf"
        counter += 1

    new_doc.save(out_path, garbage=4, deflate=True)
    new_doc.close()
    return out_path


def main():
    parser = argparse.ArgumentParser(
        prog="pdfchap",
        description="Extract chapters from a PDF into separate files using its bookmarks.",
    )
    parser.add_argument("pdf", type=Path, help="Path to the source PDF file")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (defaults to ./<book_name>_chapters)",
    )
    parser.add_argument(
        "-c",
        "--chapters",
        action="store_true",
        help="Smart mode: extract full chapters (auto-recovers chapters hidden under Part bookmarks)",
    )
    parser.add_argument(
        "-l",
        "--level",
        type=int,
        default=None,
        help="Max bookmark hierarchy level to display",
    )
    parser.add_argument(
        "-m",
        "--match",
        type=str,
        default=None,
        help="Non-interactive: extract chapters matching this regex/substring",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Non-interactive: extract all chapters matching the active filters",
    )

    args = parser.parse_args()

    if not args.pdf.exists() or not args.pdf.is_file():
        print(f"Error: PDF file not found at '{args.pdf}'", file=sys.stderr)
        sys.exit(1)

    try:
        doc = fitz.open(args.pdf)
    except Exception as e:
        print(f"Error opening PDF: {e}", file=sys.stderr)
        sys.exit(1)

    full_toc = doc.get_toc()
    chapters = parse_chapters(doc, smart_chapters=args.chapters)

    if not chapters:
        print("No matching bookmarks found in this PDF.", file=sys.stderr)
        doc.close()
        sys.exit(1)

    if args.level is not None and not args.chapters:
        chapters = [c for c in chapters if c["level"] <= args.level]

    if args.all:
        selected = chapters
    elif args.match:
        pattern = re.compile(args.match, re.IGNORECASE)
        selected = [c for c in chapters if pattern.search(c["title"])]
        if not selected:
            print(f"No chapters matched '{args.match}'.")
            doc.close()
            sys.exit(0)
    else:
        min_level = min(c["level"] for c in chapters)
        choices = []
        for c in chapters:
            indent = "  " * (c["level"] - min_level)
            page_count = c["end"] - c["start"] + 1
            label = f"{indent}{c['title']}  [pp. {c['start'] + 1}–{c['end'] + 1} | {page_count}p]"
            choices.append(questionary.Choice(title=label, value=c))

        try:
            selected = questionary.checkbox(
                "Select chapters to extract (Space = toggle, Enter = confirm, Ctrl+C = cancel):",
                choices=choices,
            ).ask()
        except KeyboardInterrupt:
            selected = None

        if not selected:
            print("Cancelled — no chapters extracted.")
            doc.close()
            sys.exit(0)

    out_dir = args.out_dir or Path(f"{args.pdf.stem}_chapters")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nExtracting {len(selected)} chapter(s) to '{out_dir.resolve()}'...")
    for c in selected:
        out_file = extract_chapter(doc, c, full_toc, out_dir)
        page_count = c["end"] - c["start"] + 1
        print(f"  ✔ {out_file.name} ({page_count} pages)")

    doc.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
