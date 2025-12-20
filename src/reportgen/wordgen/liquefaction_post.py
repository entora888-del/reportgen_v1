from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterable

from lxml import etree


_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}


def _update_alpha_runs(paragraph: etree._Element, accelerations: Iterable[int]) -> None:
    acc_list = list(sorted(accelerations))
    if not acc_list:
        return
    first = acc_list[0]
    rest = acc_list[1:]
    for node in paragraph.xpath('.//m:t', namespaces=_NS):
        text = node.text or ""
        if text.startswith("max="):
            node.text = f"max={first}"
        elif text.startswith(","):
            node.text = "," + ",".join(str(v) for v in rest) if rest else ""


def _update_dcy_paragraph(paragraph: etree._Element, value: str, degree: str) -> None:
    for node in paragraph.xpath('.//w:t', namespaces=_NS):
        text = node.text or ""
        if text == "0.00":
            node.text = value
        elif text == "なし":
            node.text = degree


def _update_pl_paragraph(paragraph: etree._Element, value: str, risk: str) -> None:
    risk_consumed = False
    for node in paragraph.xpath('.//w:t', namespaces=_NS):
        text = node.text or ""
        if text.startswith("＝") and "0.00" in text:
            node.text = f"＝{value}"
        elif not risk_consumed and ("かなり" in text or "低い" in text or "高い" in text or "極めて" in text or "低" in text):
            node.text = risk
            risk_consumed = True
        elif risk_consumed and "低い" in text:
            # 既存レイアウトでは直後のテキストに終端の括弧が含まれる
            node.text = "」"


def postprocess_liquefaction_block(doc_path: str | Path, liq_result: dict | None) -> None:
    if not liq_result:
        return

    cases = liq_result.get("cases") or {}
    if not cases:
        return

    alpha_values = liq_result.get("alpha_values") or sorted(cases.keys())
    worst_dcy = liq_result.get("worst_displacement_case")
    worst_pl = liq_result.get("worst_pl_case")
    worst_risk_case = liq_result.get("worst_risk_case") or worst_pl

    if not (worst_dcy and worst_pl and worst_risk_case):
        return

    dcy_value = f"{worst_dcy.displacement:.2f}"
    dcy_degree = worst_dcy.degree
    pl_value = f"{worst_pl.pl_value:.2f}"
    pl_risk = worst_risk_case.risk

    doc_path = Path(doc_path)
    with zipfile.ZipFile(doc_path, "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}

    document_xml = files.get("word/document.xml")
    if not document_xml:
        return

    root = etree.fromstring(document_xml)

    for paragraph in root.xpath('.//w:p', namespaces=_NS):
        text = ''.join(paragraph.xpath('.//w:t/text()', namespaces=_NS))
        math_text = ''.join(paragraph.xpath('.//m:t/text()', namespaces=_NS))
        if "液状化の程度" in text and "Dcy" in math_text:
            _update_alpha_runs(paragraph, alpha_values)
            _update_dcy_paragraph(paragraph, dcy_value, dcy_degree)
        elif "液状化危険度" in text and "PL" in math_text:
            _update_alpha_runs(paragraph, alpha_values)
            _update_pl_paragraph(paragraph, pl_value, pl_risk)
        elif "液状化しないと判定される" in text and "Fl" in math_text:
            _update_alpha_runs(paragraph, alpha_values)

    files["word/document.xml"] = etree.tostring(
        root, encoding="utf-8", xml_declaration=True, standalone="yes"
    )

    with zipfile.ZipFile(doc_path, "w") as zout:
        for name, data in files.items():
            zout.writestr(name, data)
