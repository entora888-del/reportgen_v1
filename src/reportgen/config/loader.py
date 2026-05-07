from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from copy import deepcopy


_DEFAULT_SETTINGS: dict[str, Any] = {
    "company": {
        "address": "",
        "tel": "",
        "fax": "",
    },
    "text_defaults": {},
    "report_defaults": {},
}


@dataclass(frozen=True)
class CompanySettings:
    address: str
    tel: str
    fax: str


@dataclass(frozen=True)
class TextDefaults:
    survey_purpose_template: str
    area_location_overview: str
    area_hydrology_overview: str
    area_geology_overview: str
    area_surface_overview: str
    drilling_summary: str
    foundation_consideration_top: str
    foundation_consideration_bottom: str
    groundwater_overview: str
    liq_summary_text: str
    liq_conclusion_text: str
    liq_risk_evaluation: str


@dataclass(frozen=True)
class ReportDefaults:
    survey_quantity_boring_count: int
    survey_quantity_spt_count: int
    survey_quantity_liq: str
    field_staff_suffix: str
    natural_drilling_depth: str
    groundwater_status: str
    groundwater_note: str
    liquefaction_ground_displacement: List[str]
    liquefaction_degree: List[str]
    liquefaction_index: List[str]
    liquefaction_risk: List[str]
    layer_defaults: List[dict[str, str]]


@dataclass(frozen=True)
class Settings:
    company: CompanySettings
    text_defaults: TextDefaults
    report_defaults: ReportDefaults


def _load_json_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def settings_path() -> Path:
    """設定ファイル（settings.json）のパスを返す"""
    return Path(__file__).resolve().parent / "settings.json"


def save_company_settings(address: str, tel: str, fax: str) -> None:
    """
    会社情報のみを更新して settings.json に保存する。
    他セクションは上書きしない。
    """
    path = settings_path()
    raw = _load_json_settings(path)
    if not raw:
        raw = deepcopy(_DEFAULT_SETTINGS)
    else:
        raw = _DEFAULT_SETTINGS | raw
    raw["company"] = {
        "address": str(address or "").strip(),
        "tel": str(tel or "").strip(),
        "fax": str(fax or "").strip(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings() -> Settings:
    config_dir = Path(__file__).resolve().parent
    raw = _DEFAULT_SETTINGS | _load_json_settings(config_dir / "settings.json")
    company_raw = raw.get("company", {})
    company = CompanySettings(
        address=str(company_raw.get("address", "")).strip(),
        tel=str(company_raw.get("tel", "")).strip(),
        fax=str(company_raw.get("fax", "")).strip(),
    )
    text_raw = raw.get("text_defaults", {})
    texts = TextDefaults(
        survey_purpose_template=str(text_raw.get("survey_purpose_template", "")).strip(),
        area_location_overview=str(text_raw.get("area_location_overview", "")).strip(),
        area_hydrology_overview=str(text_raw.get("area_hydrology_overview", "")).strip(),
        area_geology_overview=str(text_raw.get("area_geology_overview", "")).strip(),
        area_surface_overview=str(text_raw.get("area_surface_overview", "")).strip(),
        drilling_summary=str(text_raw.get("drilling_summary", "")).strip(),
        foundation_consideration_top=str(text_raw.get("foundation_consideration_top", "")).strip(),
        foundation_consideration_bottom=str(text_raw.get("foundation_consideration_bottom", "")).strip(),
        liq_summary_text=str(text_raw.get("liq_summary_text", "")).strip(),
        liq_conclusion_text=str(text_raw.get("liq_conclusion_text", "")).strip(),
        groundwater_overview=str(text_raw.get("groundwater_overview", "").strip()),
        liq_risk_evaluation=str(text_raw.get("liq_risk_evaluation", "")).strip(),
    )
    report_raw = raw.get("report_defaults", {})
    def _ensure_list(values, length):
        seq = list(values) if isinstance(values, (list, tuple)) else []
        if len(seq) < length:
            seq = seq + [""] * (length - len(seq))
        return [str(v).strip() for v in seq[:length]]

    layer_defaults_raw = report_raw.get("layer_defaults", [])
    layer_defaults: List[dict[str, str]] = []
    if isinstance(layer_defaults_raw, list):
        for item in layer_defaults_raw:
            if not isinstance(item, dict):
                continue
            layer_defaults.append(
                {
                    "header": str(item.get("header", "") or ""),
                    "observation": str(item.get("observation", "") or ""),
                    "n_sentence": str(item.get("n_sentence", "") or ""),
                }
            )

    report = ReportDefaults(
        survey_quantity_boring_count=int(report_raw.get("survey_quantity_boring_count", 0) or 0),
        survey_quantity_spt_count=int(report_raw.get("survey_quantity_spt_count", 0) or 0),
        survey_quantity_liq=str(report_raw.get("survey_quantity_liq", "")).strip(),
        field_staff_suffix=str(report_raw.get("field_staff_suffix", "")).strip(),
        natural_drilling_depth=str(report_raw.get("natural_drilling_depth", "")).strip(),
        groundwater_status=str(report_raw.get("groundwater_status", "")).strip(),
        groundwater_note=str(report_raw.get("groundwater_note", "")).strip(),
        liquefaction_ground_displacement=_ensure_list(report_raw.get("liquefaction_ground_displacement", []), 3),
        liquefaction_degree=_ensure_list(report_raw.get("liquefaction_degree", []), 3),
        liquefaction_index=_ensure_list(report_raw.get("liquefaction_index", []), 3),
        liquefaction_risk=_ensure_list(report_raw.get("liquefaction_risk", []), 3),
        layer_defaults=layer_defaults,
    )
    return Settings(company=company, text_defaults=texts, report_defaults=report)
