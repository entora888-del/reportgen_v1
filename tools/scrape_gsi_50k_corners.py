from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

TOP_URL = "https://www.gsi.go.jp/MAP/NEWOLDBL/25000-50000/index25000-50000.html"
USER_AGENT = "reportgen-scraper/0.1 (+https://www.gsi.go.jp/)"
REQUEST_INTERVAL = 0.8  # polite crawl: ~1 req/sec
MAX_RETRIES = 3

CORNER_ALIASES = {
    "ul": ["北西", "左上", "northwest", "nw", "上左"],
    "ur": ["北東", "右上", "northeast", "ne", "上右"],
    "lr": ["南東", "右下", "southeast", "se", "下右"],
    "ll": ["南西", "左下", "southwest", "sw", "下左"],
}


@dataclass
class CornerRow:
    code: str
    name: str
    lat_ul: float
    lon_ul: float
    lat_ur: float
    lon_ur: float
    lat_lr: float
    lon_lr: float
    lat_ll: float
    lon_ll: float
    source_url: str


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def parse_dms(value: str) -> float:
    """
    Converts strings like '34°56′07″' or '34-56-07.5' or decimal strings to float degrees.
    """
    if value is None:
        raise ValueError("empty angle")
    text = value.strip()
    if not text:
        raise ValueError("empty angle")
    text = (
        text.replace("度", "°")
        .replace("分", "'")
        .replace("′", "'")
        .replace("’", "'")
        .replace("″", '"')
        .replace("秒", '"')
        .replace("：", ":")
        .replace("･", ".")
    )
    # already decimal?
    try:
        return float(text)
    except ValueError:
        pass

    pattern = r"(-?\d+(?:\.\d+)?)"
    parts = re.findall(pattern, text.replace(":", " ").replace("-", " "))
    if not parts:
        raise ValueError(f"角度を解釈できません: {value}")
    numbers = list(map(float, parts))
    deg = numbers[0]
    minutes = numbers[1] if len(numbers) > 1 else 0.0
    seconds = numbers[2] if len(numbers) > 2 else 0.0
    sign = -1 if deg < 0 else 1
    deg = abs(deg)
    return sign * (deg + minutes / 60.0 + seconds / 3600.0)


def fetch_url(url: str, session: requests.Session, retries: int = MAX_RETRIES) -> Optional[str]:
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            time.sleep(REQUEST_INTERVAL)
    return None


def discover_pages(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".html"):
            continue
        if "25000-50000" not in href and not href.startswith("./"):
            continue
        if href.startswith("http"):
            target = href
        else:
            target = requests.compat.urljoin(base_url, href)
        if target not in links:
            links.append(target)
    return links


def match_header(headers: List[str], key_words: Iterable[str]) -> Optional[int]:
    for idx, header in enumerate(headers):
        text = normalize_text(header)
        if all(word in text for word in key_words):
            return idx
    return None


def identify_corner_columns(headers: List[str]) -> Dict[Tuple[str, str], int]:
    """
    Returns mapping { (corner, axis) : column_index } axis in {'lat','lon'}
    """
    mapping: Dict[Tuple[str, str], int] = {}
    for idx, header in enumerate(headers):
        text = normalize_text(header)
        axis = None
        if "緯" in text or "lat" in text:
            axis = "lat"
        elif "経" in text or "lon" in text:
            axis = "lon"
        else:
            continue
        for corner, keywords in CORNER_ALIASES.items():
            if any(k in text for k in keywords):
                mapping[(corner, axis)] = idx
                break
    return mapping


def parse_table(table, url: str) -> List[CornerRow]:
    header_cells = table.find_all("th")
    if not header_cells:
        return []
    headers = [cell.get_text(strip=True) for cell in header_cells]
    code_idx = match_header(headers, ["番号"]) or match_header(headers, ["図", "番号"])
    name_idx = match_header(headers, ["図", "名"]) or match_header(headers, ["名称"])
    corner_cols = identify_corner_columns(headers)
    if code_idx is None or name_idx is None:
        return []
    required_keys = [(corner, axis) for corner in CORNER_ALIASES for axis in ("lat", "lon")]
    if not all(key in corner_cols for key in required_keys):
        return []

    rows: List[CornerRow] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(headers):
            continue
        values = [cell.get_text(strip=True) for cell in cells]
        try:
            code = values[code_idx]
            name = values[name_idx]
            coords = {}
            for corner in CORNER_ALIASES:
                lat_text = values[corner_cols[(corner, "lat")]]
                lon_text = values[corner_cols[(corner, "lon")]]
                coords[(corner, "lat")] = parse_dms(lat_text)
                coords[(corner, "lon")] = parse_dms(lon_text)
            rows.append(
                CornerRow(
                    code=code,
                    name=name,
                    lat_ul=coords[("ul", "lat")],
                    lon_ul=coords[("ul", "lon")],
                    lat_ur=coords[("ur", "lat")],
                    lon_ur=coords[("ur", "lon")],
                    lat_lr=coords[("lr", "lat")],
                    lon_lr=coords[("lr", "lon")],
                    lat_ll=coords[("ll", "lat")],
                    lon_ll=coords[("ll", "lon")],
                    source_url=url,
                )
            )
        except Exception:
            continue
    return rows


def scrape(out_csv: Path, parse_error_dir: Path, max_pages: Optional[int] = None) -> Tuple[List[CornerRow], List[str]]:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    parse_error_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    top_html = fetch_url(TOP_URL, session)
    if not top_html:
        return [], [TOP_URL]

    pages = discover_pages(top_html, TOP_URL)
    visited = 0
    rows: List[CornerRow] = []
    failures: List[str] = []

    for page_url in pages:
        if max_pages and visited >= max_pages:
            break
        visited += 1
        html = fetch_url(page_url, session)
        if not html:
            failures.append(page_url)
            (parse_error_dir / f"fetch_fail_{visited}.log").write_text(
                f"Failed to fetch {page_url}\n", encoding="utf-8"
            )
            continue
        soup = BeautifulSoup(html, "html.parser")
        page_rows = []
        for table in soup.find_all("table"):
            page_rows.extend(parse_table(table, page_url))
        if not page_rows:
            (parse_error_dir / f"parse_fail_{visited}.html").write_text(html, encoding="utf-8")
            failures.append(page_url)
        else:
            rows.extend(page_rows)
        time.sleep(REQUEST_INTERVAL)

    fieldnames = [
        "code",
        "name_ja",
        "lat_ul",
        "lon_ul",
        "lat_ur",
        "lon_ur",
        "lat_lr",
        "lon_lr",
        "lat_ll",
        "lon_ll",
        "source_url",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
    return rows, failures


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GSI 5万図 四隅座標スクレイパー")
    parser.add_argument("--out", default="tmp/50k_corners.csv", help="出力CSVパス")
    parser.add_argument("--max-pages", type=int, help="巡回するページ上限（デバッグ用）")
    parser.add_argument("--parse-error-dir", default="tmp/parse_errors", help="解析失敗時の保存先")
    parser.add_argument("--log", action="store_true", help="進捗を標準出力へ表示")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    rows, failures = scrape(Path(args.out), Path(args.parse_error_dir), args.max_pages)
    if args.log:
        print(f"Collected rows: {len(rows)}")
        if failures:
            print(f"Failures: {len(failures)} entries")
            for url in failures[:5]:
                print(" -", url)
    if not rows:
        print("No data collected. Please verify network connectivity or retry with a different max-pages value.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
