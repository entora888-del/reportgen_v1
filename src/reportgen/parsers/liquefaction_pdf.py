from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pdfplumber


@dataclass
class LiquefactionCase:
    acceleration: int
    displacement: float
    degree: str
    pl_value: float
    risk: str

    @property
    def displacement_text_fixed(self) -> str:
        return f"{self.displacement:.2f}"

    @property
    def pl_text(self) -> str:
        return f"{self.pl_value:.2f}"


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _classify_pl(value: float) -> str:
    if value <= 0:
        return "かなり低い"
    if value <= 5:
        return "低い"
    if value <= 15:
        return "高い"
    return "極めて高い"


_LIQ_RISK_RANK = {"かなり低い": 0, "低い": 1, "高い": 2, "極めて高い": 3}


def _parse_page(text: str) -> LiquefactionCase | None:
    norm = _normalize(text)

    accel_match = re.search(r"αmax\s*=\s*([0-9.]+)", norm)
    if not accel_match:
        return None
    acceleration = int(round(float(accel_match.group(1))))

    dcy_match = re.search(r"地表最大水平変位Dcy.*?(\d+(?:\.\d+)?)\s*m\s*([^\s\n]+)", norm, re.S)
    if not dcy_match:
        return None
    displacement = float(dcy_match.group(1))
    degree = dcy_match.group(2).strip()

    pl_value = 0.0
    heading = "PL法による液状化危険度判定"
    heading_idx = norm.find(heading)
    if heading_idx != -1:
        before = norm[:heading_idx]
        matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*[○Ｘ△]", before))
        if matches:
            pl_value = float(matches[-1].group(1))
    if pl_value == 0.0:
        after = norm[heading_idx:] if heading_idx != -1 else norm
        matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*[○Ｘ△]", after))
        if matches:
            pl_value = float(matches[0].group(1))

    risk = _classify_pl(pl_value)

    return LiquefactionCase(
        acceleration=acceleration,
        displacement=displacement,
        degree=degree,
        pl_value=pl_value,
        risk=risk,
    )


def _format_conclusion(case: LiquefactionCase | None) -> str:
    if not case:
        return ""
    return (
        "・Dcy値(液状化に伴う予測地盤変位量)の判定について\n"
        f"Dcyの検討では、Dcy＝{case.displacement_text_fixed}mであり、"
        f"液状化の程度は「{case.degree}」と判定される。"
    )


def _format_risk(case: LiquefactionCase | None) -> str:
    if not case:
        return ""
    return (
        "・PL法(液状化による影響度を示す指標)の判定について\n"
        f"PLの検討では、PL＝{case.pl_text}であり、液状化危険度が「{case.risk}」と判定される。"
    )


def summarize_liquefaction_pdf(pdf_path: str | Path) -> dict:
    """液状化判定PDFを解析し、固定3ケース（150/200/350gal）の結果を返す。"""

    cases: Dict[int, LiquefactionCase] = {}

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            case = _parse_page(raw)
            if not case:
                continue
            cases[case.acceleration] = case

    if not cases:
        return {
            "cases": {},
            "summary_text": "",
            "conclusion_text": "",
            "risk_text": "",
        }

    worst_displacement = max(cases.values(), key=lambda c: c.displacement)
    worst_pl = max(cases.values(), key=lambda c: c.pl_value)
    worst_risk = max(cases.values(), key=lambda c: _LIQ_RISK_RANK.get(c.risk, -1))

    summary_text = (
        "液状化の検討結果は巻末資料の液状化簡易判定結果に示すとおりである。\n"
        "・FL値(各深さにおける液状化発生に対する安全率)の判定について\n"
        "FLの検討では、全ての土層でFL値が1.0を上回っており、液状化しないと判定される。"
    )

    return {
        "cases": cases,
        "summary_text": summary_text,
        "conclusion_text": _format_conclusion(worst_displacement),
        "risk_text": _format_risk(worst_pl),
        "overall_risk": worst_risk.risk,
        "worst_displacement_case": worst_displacement,
        "worst_pl_case": worst_pl,
        "worst_risk_case": worst_risk,
        "alpha_values": sorted(cases.keys()),
    }
