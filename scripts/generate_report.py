from __future__ import annotations

import argparse
from pathlib import Path

from reportgen.parsers.liquefaction_pdf import summarize_liquefaction_pdf
from reportgen.wordgen.templater import (
    build_context_from_inputs,
    generate_docx_from_template,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a report DOCX from XML and optional liquefaction PDF.")
    parser.add_argument("--xml", required=True, help="Path to boring XML")
    parser.add_argument("--out", required=True, help="Path to output DOCX")
    parser.add_argument("--liq-pdf", default=None, help="Optional liquefaction PDF")
    parser.add_argument("--template", default=None, help="Optional template DOCX")
    args = parser.parse_args()

    xml_path = Path(args.xml).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    liq_result: dict | None = None
    if args.liq_pdf:
        liq_path = Path(args.liq_pdf).expanduser().resolve()
        liq_result = summarize_liquefaction_pdf(liq_path)

    context = build_context_from_inputs(str(xml_path))
    generate_docx_from_template(
        args.template,
        str(out_path),
        context,
        liq_result=liq_result,
        source_xml_path=str(xml_path),
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
