from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

import geopandas as gpd
import requests
from pyproj import Geod
from shapely.geometry import Point

from reportgen.parsers.boring_xml import extract_latlon_from_xml

BOOKLET_URL_TEMPLATE = "https://nlftp.mlit.go.jp/kokjo/tochimizu/F3/data/pdf/{code}t.pdf"
SOURCE_TEXT = (
    "出典：国土交通省「土地分類基本調査（5万分の1）」簿冊（t.pdf）\n"
    # "取得URLは図幅コードに基づく定形パス（…/F3/data/pdf/{code}t.pdf）\n"
    # "利用条件は配布元の規定に従うこと（転載・改変の可否に注意）"
)

GEOD = Geod(ellps="GRS80")
WGS84_EPSG = "EPSG:4326"
METRIC_EPSG = "EPSG:3857"


@dataclass
class BookletCandidate:
    code: str
    name: str
    distance_m: float
    url: str
    attempted: bool = False
    success: bool = False
    saved_path: Optional[Path] = None
    error: Optional[str] = None


@dataclass
class BookletFetchParams:
    index_path: Path
    out_dir: Path
    xml_path: Optional[Path]
    address: str
    candidate_count: int
    buffer_m: float
    select_mode: str
    code_field: str
    name_field: str


@dataclass
class BookletFetchResult:
    lat: float
    lon: float
    candidates: List[BookletCandidate]


def _geocode_address_stub(address: str) -> Optional[tuple[float, float]]:
    # 住所ジオコーディングはスタブ。実装先が無いため None を返し、GUI側で案内する。
    return None


def _load_index(index_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(index_path)
    if gdf.empty:
        raise ValueError("インデックスファイルに地物がありません。")
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84_EPSG)
    else:
        gdf = gdf.to_crs(WGS84_EPSG)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notnull()]
    if gdf.empty:
        raise ValueError("利用できる図幅ポリゴンが見つかりませんでした。")
    return gdf


def _point_metric(point: Point) -> Point:
    import pyproj
    from shapely.ops import transform

    transformer = pyproj.Transformer.from_crs(WGS84_EPSG, METRIC_EPSG, always_xy=True)
    return transform(transformer.transform, point)


def _geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    _, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return float(dist)


def _extract_candidates(
    gdf: gpd.GeoDataFrame,
    point_wgs: Point,
    code_field: str,
    name_field: str,
    candidate_count: int,
    buffer_m: float,
) -> List[BookletCandidate]:
    metric_point = _point_metric(point_wgs)
    gdf_metric = gdf.to_crs(METRIC_EPSG)

    def _contains_or_on_boundary(geom):
        try:
            if geom.contains(point_wgs):
                return True
            return geom.distance(point_wgs) == 0.0
        except Exception:
            return False

    mask_within = gdf.geometry.apply(_contains_or_on_boundary)
    candidate_indices: Sequence[int] = gdf[mask_within].index

    if len(candidate_indices) == 0 and buffer_m > 0:
        buffer_geom = metric_point.buffer(max(buffer_m, 0.0))
        mask_buffer = gdf_metric.geometry.intersects(buffer_geom)
        candidate_indices = gdf_metric[mask_buffer].index

    if len(candidate_indices) == 0:
        candidate_indices = gdf.index

    candidates: List[BookletCandidate] = []
    for idx in candidate_indices:
        row = gdf.loc[idx]
        code_val = _normalize_code(row.get(code_field, "") or row.get("code", ""))
        name_val = str(row.get(name_field, "") or row.get("name", "")).strip()
        if not code_val:
            continue
        if not name_val:
            name_val = "-"
        centroid = row.geometry.centroid
        distance = _geodesic_distance_m(point_wgs.y, point_wgs.x, centroid.y, centroid.x)
        url = BOOKLET_URL_TEMPLATE.format(code=code_val)
        candidates.append(BookletCandidate(code=code_val, name=name_val, distance_m=distance, url=url))

    candidates.sort(key=lambda c: c.distance_m)
    if candidate_count > 0:
        candidates = candidates[:candidate_count]
    return candidates


def _download_pdf(url: str, save_path: Path, timeout: int = 30) -> None:
    headers = {"User-Agent": "reportgen/0.1"}
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                fh.write(chunk)


def _normalize_code(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    # Handle floats like 2806.0 -> 2806
    try:
        num = float(text)
        if abs(num - round(num)) < 1e-6:
            text = str(int(round(num)))
    except ValueError:
        pass
    return text


def fetch_booklets(
    params: BookletFetchParams,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> BookletFetchResult:
    progress = progress_cb or (lambda _msg: None)

    latlon: Optional[tuple[float, float]] = None
    if params.xml_path and params.xml_path.exists():
        progress("XML から座標を抽出しています…")
        latlon = extract_latlon_from_xml(params.xml_path)

    if not latlon and params.address:
        progress("住所から座標を推定しています（スタブ）…")
        latlon = _geocode_address_stub(params.address)

    if not latlon:
        raise ValueError("座標を取得できませんでした。XMLに緯度経度があるか確認してください。")

    lat, lon = latlon
    point_wgs = Point(lon, lat)

    progress("インデックスを読み込んでいます…")
    gdf = _load_index(params.index_path)
    if params.code_field not in gdf.columns and "code" not in gdf.columns:
        raise ValueError(f"図幅コード列 '{params.code_field}' が見つかりません。")
    if params.name_field not in gdf.columns and "name" not in gdf.columns:
        progress("図幅名列が見つからなかったため空欄になります。")

    candidate_count = max(1, params.candidate_count)
    buffer_m = max(0.0, params.buffer_m)

    progress("候補となる図幅を抽出しています…")
    candidates = _extract_candidates(
        gdf,
        point_wgs,
        code_field=params.code_field or "code",
        name_field=params.name_field or "name",
        candidate_count=candidate_count,
        buffer_m=buffer_m,
    )

    if not candidates:
        raise ValueError("候補が見つかりませんでした。バッファ距離や列名を見直してください。")

    select_all = params.select_mode.lower() == "all"
    targets = candidates if select_all else candidates[:1]

    for cand in targets:
        cand.attempted = True
        save_path = params.out_dir / f"{cand.code}t.pdf"
        progress(f"{cand.code}t.pdf を取得しています…")
        try:
            _download_pdf(cand.url, save_path)
            cand.success = True
            cand.saved_path = save_path
        except Exception as exc:
            cand.error = str(exc)

    return BookletFetchResult(lat=lat, lon=lon, candidates=candidates)
