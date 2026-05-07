from __future__ import annotations

import argparse
import difflib
from pathlib import Path
from typing import Iterable

from docx import Document

from reportgen.parsers.liquefaction_pdf import summarize_liquefaction_pdf
from reportgen.wordgen.templater import (
    build_context_from_inputs,
    generate_docx_from_template,
)


def extract_text_lines(doc_path: Path) -> list[str]:
    doc = Document(str(doc_path))
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    return lines


def find_expected_docx(sample_dir: Path) -> Path | None:
    docxs = sorted(sample_dir.glob("*.docx"))
    return docxs[0] if docxs else None


def find_liq_pdf(sample_dir: Path) -> Path | None:
    for pattern in ("液状化.pdf", "*液状化*.pdf"):
        hits = sorted(sample_dir.glob(pattern))
        if hits:
            return hits[0]
    return None


def summarize_diff(expected_lines: list[str], generated_lines: list[str]) -> tuple[int, float]:
    matcher = difflib.SequenceMatcher(a=expected_lines, b=generated_lines)
    diff_count = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            diff_count += (i2 - i1) + (j2 - j1)
    return diff_count, matcher.ratio()


def write_unified_diff(
    expected_lines: Iterable[str],
    generated_lines: Iterable[str],
    out_path: Path,
    from_name: str,
    to_name: str,
) -> None:
    diff = difflib.unified_diff(
        list(expected_lines),
        list(generated_lines),
        fromfile=from_name,
        tofile=to_name,
        lineterm="",
    )
    out_path.write_text("\n".join(diff), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate DOCX for samples and diff against references.")
    parser.add_argument("--samples-root", default="data/samples", help="Root directory containing numbered sample folders")
    parser.add_argument("--out-dir", default="tmp/compare_results", help="Directory to store generated docs and diffs")
    parser.add_argument("--exclude", default="", help="Comma-separated sample folder names to skip")
    args = parser.parse_args()

    samples_root = Path(args.samples_root).expanduser()
    out_root = Path(args.out_dir).expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    exclude = {item.strip() for item in args.exclude.split(",") if item.strip()}

    for sample_dir in sorted(path for path in samples_root.iterdir() if path.is_dir()):
        xml_path = sample_dir / "DATA.XML"
        if not xml_path.exists():
            continue
        if sample_dir.name in exclude:
            summary_lines.append(f"{sample_dir.name}: skipped (exclude list)")
            continue

        expected_docx = find_expected_docx(sample_dir)
        liq_pdf = find_liq_pdf(sample_dir)
        generated_path = out_root / f"{sample_dir.name}_generated.docx"
        diff_path = out_root / f"{sample_dir.name}_diff.txt"

        liq_result = {}
        if liq_pdf and liq_pdf.exists():
            try:
                liq_result = summarize_liquefaction_pdf(liq_pdf)
            except Exception:
                liq_result = {}

        context = build_context_from_inputs(str(xml_path))
        generate_docx_from_template(None, str(generated_path), context, liq_result=liq_result, source_xml_path=str(xml_path))

        if expected_docx and expected_docx.exists():
            expected_lines = extract_text_lines(expected_docx)
            generated_lines = extract_text_lines(generated_path)
            diff_count, ratio = summarize_diff(expected_lines, generated_lines)
            write_unified_diff(expected_lines, generated_lines, diff_path, "expected", "generated")
            summary_lines.append(
                f"{sample_dir.name}: expected={len(expected_lines)} lines, generated={len(generated_lines)} lines, diff_count={diff_count}, similarity={ratio:.3f}"
            )
        else:
            summary_lines.append(f"{sample_dir.name}: expected DOCX not found; generated={generated_path}")

    summary_path = out_root / "summary.txt"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
