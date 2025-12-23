# src/reportgen/parsers/boring_xml.py
from __future__ import annotations
from pathlib import Path
from lxml import etree
from datetime import datetime
from typing import Optional, Tuple

def _format_ymd(date_text: str) -> str:
    if not date_text:
        return ""
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return f"{dt.year}年{dt.month}月{dt.day}日"

def _format_md(date_text: str) -> str:
    if not date_text:
        return ""
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return date_text
    return f"{dt.month}/{dt.day}"

def _format_depth(value: str) -> str:
    if not value:
        return ""
    try:
        num = float(value)
    except ValueError:
        return value
    return f"{num:.2f}"

def _text(root, xpath):
    v = root.findtext(xpath)
    return v.strip() if v else ""


def _parse_xml_with_fallback(xml_path: str | Path):
    """
    Parse XML with recovery, trying UTF-8 first and then Shift_JIS variants.
    """
    path = Path(xml_path)

    # 1) Try default parser (auto-detect)
    try:
        return etree.parse(str(path), etree.XMLParser(recover=True)).getroot()
    except (UnicodeDecodeError, etree.XMLSyntaxError):
        pass

    # 2) Try Shift_JIS/CP932 decodes and re-parse as UTF-8
    raw = path.read_bytes()
    for enc in ("shift_jis", "cp932", "shift_jisx0213"):
        try:
            text = raw.decode(enc, errors="replace")
        except UnicodeDecodeError:
            continue
        try:
            return etree.fromstring(text.encode("utf-8"), parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            continue

    # If still failing, raise a descriptive error
    raise etree.XMLSyntaxError("XML decoding failed (tried UTF-8 and Shift_JIS family)", 0, 0, 0, 0)

def _dms_to_decimal(deg: str | float | None, minute: str | float | None, second: str | float | None) -> Optional[float]:
    try:
        d = float(deg)
        m = float(minute) if minute is not None and minute != "" else 0.0
        s = float(second) if second is not None and second != "" else 0.0
    except (TypeError, ValueError):
        return None
    sign = -1.0 if d < 0 else 1.0
    d = abs(d)
    return sign * (d + m / 60.0 + s / 3600.0)

def extract_latlon_from_xml(xml_path: str | Path) -> Optional[Tuple[float, float]]:
    """
    Returns (lat, lon) in decimal degrees if the XML contains 経度緯度情報.
    """
    root = _parse_xml_with_fallback(xml_path)
    lon_deg = _text(root, ".//経度緯度情報/経度_度")
    lon_min = _text(root, ".//経度緯度情報/経度_分")
    lon_sec = _text(root, ".//経度緯度情報/経度_秒")
    lat_deg = _text(root, ".//経度緯度情報/緯度_度")
    lat_min = _text(root, ".//経度緯度情報/緯度_分")
    lat_sec = _text(root, ".//経度緯度情報/緯度_秒")

    lon = _dms_to_decimal(lon_deg, lon_min, lon_sec)
    lat = _dms_to_decimal(lat_deg, lat_min, lat_sec)

    if lon is None or lat is None:
        return None
    return (lat, lon)

def extract_cover_from_xml(xml_path: str | Path) -> dict:
    root = _parse_xml_with_fallback(xml_path)
    title = _text(root, ".//標題情報/調査基本情報/調査名")
    start = _text(root, ".//標題情報/調査期間/調査期間_開始年月日")
    ym = ""
    if start:
        dt = datetime.strptime(start, "%Y-%m-%d")
        ym = f"{dt.year}年{dt.month}月"
    company = _text(root, ".//標題情報/調査会社/調査会社_名称")
    return {
        "cover_title": title,
        "cover_date_ym": ym,
        "cover_company_name": company,
    }

def extract_report_metadata(xml_path: str | Path) -> dict:
    root = _parse_xml_with_fallback(xml_path)
    start = _text(root, ".//標題情報/調査期間/調査期間_開始年月日")
    end = _text(root, ".//標題情報/調査期間/調査期間_終了年月日")
    address = _text(root, ".//標題情報/調査位置/調査位置住所")
    location = f"{address}　地内" if address else ""
    company_name = _text(root, ".//標題情報/調査会社/調査会社_名称")
    tel = _text(root, ".//標題情報/調査会社/調査会社_TEL")
    chief_name = _text(root, ".//標題情報/調査会社/調査会社_主任技師_氏名")
    chief_license = _text(root, ".//標題情報/調査会社/調査会社_主任技師_地質調査技士登録番号")
    agent_name = _text(root, ".//標題情報/調査会社/調査会社_現場代理人_氏名")
    agent_license = _text(root, ".//標題情報/調査会社/調査会社_現場代理人_地質調査技士登録番号")
    field_supervisor = _text(root, ".//標題情報/調査会社/調査会社_ボーリング責任者_氏名")
    borehole_name = _text(root, ".//標題情報/調査基本情報/ボーリング名")
    total_depth = _text(root, ".//総削孔長") or _text(root, ".//削孔工程/削孔工程_削孔深度")
    ground_elevation = _text(root, ".//孔口標高")
    groundwater_depth = _text(root, ".//孔内水位/孔内水位_孔内水位")
    groundwater_date = _text(root, ".//孔内水位/孔内水位_測定年月日")

    elevation_ref = ""
    for node in root.findall(".//フリー情報"):
        txt = (node.text or "").strip()
        if not txt:
            continue
        stripped = txt.strip("[]")
        if "：" not in stripped:
            continue
        key, value = stripped.split("：", 1)
        if key.strip() == "標高基準":
            elevation_ref = value.strip()
            break

    elevation_display = ""
    if ground_elevation:
        formatted = _format_depth(ground_elevation)
        if elevation_ref:
            sign = "+" if not formatted.startswith(("+", "-")) else ""
            elevation_display = f"{elevation_ref}{sign}{formatted}"
        else:
            elevation_display = formatted

    return {
        "survey_name": _text(root, ".//標題情報/調査基本情報/調査名"),
        "survey_location": location,
        "survey_period_start": _format_ymd(start),
        "survey_period_end": _format_ymd(end),
        "survey_company_name": company_name or _text(root, ".//標題情報/調査会社/調査会社名"),
        "survey_company_tel_xml": tel,
        "survey_staff_lead_name": chief_name,
        "survey_staff_lead_license": chief_license,
        "survey_staff_agent_name": agent_name,
        "survey_staff_agent_license": agent_license,
        "survey_staff_field_name": field_supervisor,
        "borehole_name": borehole_name,
        "drilling_length": _format_depth(total_depth),
        "borehole_elevation": elevation_display,
        "groundwater_depth": _format_depth(groundwater_depth),
        "groundwater_date_md": _format_md(groundwater_date),
        "drilling_direction": "",
        "natural_drilling_depth": "",
        "groundwater_note": "",
    }

def parse_boring_xml(xml_path: str | Path) -> dict:
    """
    site_name: ボーリング名 + 住所（例: 'No.1（兵庫県加東市東古瀬）'）
    groundwater: '2.76 m（YYYY-MM-DD 測定）'
    layers: [{name, top, bottom, thickness, observation, N_values}]
    """
    root = _parse_xml_with_fallback(xml_path)

    # 地点名
    borehole = _text(root, ".//標題情報/調査基本情報/ボーリング名")
    addr = _text(root, ".//標題情報/調査位置/調査位置住所")
    site_name = f"{borehole}（{addr}）" if addr else borehole

    # 地下水位
    gw = _text(root, ".//コア情報/孔内水位/孔内水位_孔内水位")
    gwd = _text(root, ".//コア情報/孔内水位/孔内水位_測定年月日")
    groundwater = f"{gw} m（{gwd}測定）" if gw else ""

    # 層境界と名称（下端深度で区切り、最上層上端は0.00）
    layers_raw = root.findall(".//コア情報/工学的地質区分名現場土質名")
    bounds = []
    prev = 0.0
    for node in layers_raw:
        bottom = float(_text(node, "./工学的地質区分名現場土質名_下端深度") or "0")
        name = _text(node, "./工学的地質区分名現場土質名_工学的地質区分名現場土質名")
        bounds.append({"top": prev, "bottom": bottom, "name": name})
        prev = bottom

    observations = []
    for node in root.findall(".//コア情報/観察記事"):
        top = float((node.findtext("観察記事_上端深度") or "0").strip() or "0")
        bottom = float((node.findtext("観察記事_下端深度") or "0").strip() or "0")
        text = node.findtext("観察記事_記事") or ""
        text = text.replace("¥n", "\n").strip()
        observations.append({"top": top, "bottom": bottom, "text": text})

    # SPT から N 値（N = (100-200) + (200-300)）
    spts = []
    for s in root.findall(".//コア情報/標準貫入試験"):
        start = float(_text(s, "./標準貫入試験_開始深度") or "0")
        total = _text(s, "./標準貫入試験_合計打撃回数")
        if total:
            try:
                n_val = int(round(float(total)))
            except ValueError:
                continue
        else:
            a = _text(s, "./標準貫入試験_100_200打撃回数")
            b = _text(s, "./標準貫入試験_200_300打撃回数")
            n_val = 0
            if a:
                n_val += int(a)
            if b:
                n_val += int(b)
        spts.append({"z": start, "N": n_val})

    # 試験開始深度が属する層にNを集計→平均
    def belongs(z, top, bottom):
        return (z >= top) and (z < bottom or abs(z - bottom) < 1e-6)

    def find_observation(top: float, bottom: float) -> str:
        for ob in observations:
            if abs(ob["top"] - top) < 1e-6 and abs(ob["bottom"] - bottom) < 1e-6:
                return ob["text"]
        return ""

    result_layers = []
    for b in bounds:
        Ns = [sp["N"] for sp in spts if belongs(sp["z"], b["top"], b["bottom"])]
        thickness = b["bottom"] - b["top"]
        result_layers.append({
            "name": b["name"],
            "top": b["top"],
            "bottom": b["bottom"],
            "thickness": thickness if thickness >= 0 else None,
            "observation": find_observation(b["top"], b["bottom"]),
            "N_values": Ns,
        })

    return {
        "site_name": site_name,
        "groundwater": groundwater,
        "layers": result_layers,
        "spt_records": spts,
    }
