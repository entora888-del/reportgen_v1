from __future__ import annotations

import argparse
import json
import logging
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

LOG = logging.getLogger("build_50k_index")

CORNER_ORDER = ("ul", "ur", "lr", "ll")
WGS84 = "EPSG:4326"
TOKYO = "EPSG:4301"
METRIC = "EPSG:3857"


@dataclass
class LoadResult:
    data: pd.DataFrame | gpd.GeoDataFrame
    mode: str  # "corners" or "geometry"


def detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".csv",):
        return "csv"
    if ext in (".tsv",):
        return "tsv"
    if ext in (".json",):
        return "json"
    if ext in (".geojson",):
        return "geojson"
    if ext in (".gpkg",):
        return "gpkg"
    raise ValueError(f"拡張子から形式を判定できません: {path}")


def load_source(path: Path, fmt: str, layer: Optional[str]) -> LoadResult:
    if fmt == "csv":
        df = pd.read_csv(path)
        return LoadResult(df, "corners")
    if fmt == "tsv":
        df = pd.read_csv(path, sep="\t")
        return LoadResult(df, "corners")
    if fmt == "json":
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict) and "features" in data:
            gdf = gpd.read_file(path)
            return LoadResult(gdf, "geometry")
        df = pd.DataFrame(data)
        return LoadResult(df, "corners")
    if fmt in ("geojson", "gpkg"):
        kwargs = {}
        if layer:
            kwargs["layer"] = layer
        gdf = gpd.read_file(path, **kwargs)
        return LoadResult(gdf, "geometry")
    raise ValueError(f"未対応の入力形式です: {fmt}")


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(f"必要な列が不足しています: {', '.join(missing)}")


def to_wgs84(data: pd.DataFrame | gpd.GeoDataFrame, mode: str, datum: str) -> pd.DataFrame | gpd.GeoDataFrame:
    if datum.lower() == "wgs84":
        if mode == "geometry":
            gdf = gpd.GeoDataFrame(data)
            if gdf.crs is None:
                gdf.set_crs(WGS84, inplace=True)
            return gdf
        return data

    if datum.lower() != "tokyo":
        raise ValueError(f"未対応の測地系です: {datum}")

    if mode == "geometry":
        gdf = gpd.GeoDataFrame(data)
        if gdf.crs is None:
            gdf.set_crs(TOKYO, inplace=True)
        gdf = gdf.to_crs(WGS84)
        return gdf

    df = data.copy()
    transformer = Transformer.from_crs(TOKYO, WGS84, always_xy=True)
    for corner in CORNER_ORDER:
        lat_col = f"lat_{corner}"
        lon_col = f"lon_{corner}"
        _ensure_columns(df, [lat_col, lon_col])
        lons = pd.to_numeric(df[lon_col], errors="coerce").tolist()
        lats = pd.to_numeric(df[lat_col], errors="coerce").tolist()
        x, y = transformer.transform(lons, lats)
        df[lon_col] = x
        df[lat_col] = y
    return df


def _extract_name(row: pd.Series) -> str:
    for key in ("name_ja", "name", "図幅名"):
        if key in row and pd.notna(row[key]):
            return str(row[key]).strip()
    raise ValueError("図幅名の列（name_ja, name 等）が見つかりません。")


def _extract_code(value) -> str:
    code = str(value).strip()
    if not code:
        raise ValueError("図幅コードが空です。")
    return code.zfill(4)


def build_polygons(
    data: pd.DataFrame | gpd.GeoDataFrame,
    mode: str,
) -> gpd.GeoDataFrame:
    if mode == "geometry":
        gdf = gpd.GeoDataFrame(data).copy()
        if gdf.crs is None:
            gdf.set_crs(WGS84, inplace=True)
        gdf = gdf.to_crs(WGS84)
        if "geometry" not in gdf:
            raise ValueError("geometry 列が存在しません。")
        return gdf

    df = pd.DataFrame(data).copy()
    _ensure_columns(df, ["code"])
    for corner in CORNER_ORDER:
        _ensure_columns(df, [f"lat_{corner}", f"lon_{corner}"])
    records: List[dict] = []
    for _, row in df.iterrows():
        points: List[Tuple[float, float]] = []
        for corner in CORNER_ORDER:
            lat = float(row[f"lat_{corner}"])
            lon = float(row[f"lon_{corner}"])
            points.append((lon, lat))
        points.append(points[0])
        polygon = Polygon(points)
        records.append(
            {
                "code": _extract_code(row["code"]),
                "name_ja": _extract_name(row),
                "geometry": polygon,
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=WGS84)


def _fix_geometry(geom) -> Tuple[object, bool]:
    if geom.is_valid:
        return geom, False
    fixed = geom.buffer(0)
    return fixed, True


def validate_and_fix(gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, int, List[str]]:
    gdf = gdf.reset_index(drop=True).copy()
    fix_count = 0
    warnings: List[str] = []

    if gdf.crs is None:
        gdf.set_crs(WGS84, inplace=True)
    else:
        gdf = gdf.to_crs(WGS84)

    fixed_geoms = []
    for geom in gdf.geometry:
        new_geom, fixed = _fix_geometry(geom)
        if fixed:
            fix_count += 1
        fixed_geoms.append(new_geom)
    gdf.geometry = fixed_geoms

    metric = gdf.to_crs(METRIC)
    areas = metric.area
    for idx, area in areas.items():
        if area <= 0:
            raise ValueError(f"コード {gdf.loc[idx, 'code']} の面積が0です。入力データを確認してください。")
        if area < 1e5:
            warnings.append(f"コード {gdf.loc[idx, 'code']} の面積が極端に小さい可能性があります ({area:.1f} m^2)")
        if area > 1e11:
            warnings.append(f"コード {gdf.loc[idx, 'code']} の面積が極端に大きい可能性があります ({area:.1f} m^2)")

    overlaps = 0
    if len(gdf) > 1:
        metric_geoms = metric.geometry
        sindex = metric.sindex
        for idx, geom in enumerate(metric_geoms):
            possible = sindex.query(geom, predicate="intersects")
            for jdx in possible:
                if jdx <= idx:
                    continue
                other = metric_geoms.iloc[jdx]
                inter = geom.intersection(other)
                if inter.area > 1e4:
                    overlaps += 1
        if overlaps:
            warnings.append(f"重なりが疑われる図幅ペアが {overlaps} 件あります。")

    # gap detection via random sampling inside convex hull
    union = unary_union(metric.geometry)
    if not union.is_empty:
        minx, miny, maxx, maxy = union.bounds
        sample_count = min(max(50, len(gdf) // 2), 500)
        gap_points = 0
        for _ in range(sample_count):
            x = random.uniform(minx, maxx)
            y = random.uniform(miny, maxy)
            point = Point(x, y)
            if union.contains(point):
                continue
            gap_points += 1
        if gap_points:
            warnings.append(f"ランダム検査で {gap_points} 件の隙間候補を検出しました。図郭の接続を確認してください。")

    return gdf, fix_count, warnings


def enrich_attributes(
    gdf: gpd.GeoDataFrame,
    source_text: str,
    source_url: str,
    created_at: str,
) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    if "code" not in gdf.columns:
        raise ValueError("code 列が見つかりません。")
    gdf["code"] = gdf["code"].apply(_extract_code)
    if "name_ja" not in gdf.columns:
        gdf["name_ja"] = gdf.apply(_extract_name, axis=1)
    gdf["source"] = source_text
    gdf["source_url"] = source_url
    gdf["created"] = created_at
    return gdf


def save_outputs(gdf: gpd.GeoDataFrame, out_dir: Path, layer_name: str) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = out_dir / "50k_index.geojson"
    gpkg_path = out_dir / "50k_index.gpkg"
    gdf.to_file(geojson_path, driver="GeoJSON")
    gdf.to_file(gpkg_path, driver="GPKG", layer=layer_name)
    return geojson_path, gpkg_path


def write_meta(out_dir: Path, meta: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "50k_index_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def gather_git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="5万図インデックスを作成します。")
    parser.add_argument("--src", required=True, help="入力ファイル（CSV/TSV/JSON/GPKG/GeoJSON）")
    parser.add_argument("--src-format", choices=["csv", "tsv", "json", "geojson", "gpkg"], help="入力形式を明示する場合に指定")
    parser.add_argument("--src-layer", help="GPKG 読み込み時のレイヤ名")
    parser.add_argument("--datum", choices=["wgs84", "tokyo"], default="wgs84", help="入力データの測地系")
    parser.add_argument("--out-dir", default="data/indices", help="出力ディレクトリ")
    parser.add_argument("--layer-name", default="index_50k", help="GPKG に書き込むレイヤ名")
    parser.add_argument("--source-text", default="国土地理院 図幅索引資料", help="属性に埋め込む出典テキスト")
    parser.add_argument("--source-url", default="https://www.gsi.go.jp/", help="出典URL")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")

    src_path = Path(args.src)
    if not src_path.exists():
        LOG.error("入力ファイルが見つかりません: %s", src_path)
        return 1

    fmt = args.src_format or detect_format(src_path)
    LOG.info("入力ファイル: %s (format=%s)", src_path, fmt)
    load_result = load_source(src_path, fmt, args.src_layer)
    data = to_wgs84(load_result.data, load_result.mode, args.datum)
    gdf = build_polygons(data, load_result.mode)

    created_at = datetime.now(timezone.utc).isoformat()
    gdf = enrich_attributes(gdf, args.source_text, args.source_url, created_at)
    gdf, fix_count, warnings = validate_and_fix(gdf)

    geojson_path, gpkg_path = save_outputs(gdf, Path(args.out_dir), args.layer_name)
    meta = {
        "input": str(src_path),
        "input_format": fmt,
        "datum": args.datum,
        "record_count": int(len(gdf)),
        "fix_count": fix_count,
        "warnings": warnings,
        "created": created_at,
        "source": args.source_text,
        "source_url": args.source_url,
        "layer_name": args.layer_name,
        "git_commit": gather_git_commit(),
        "outputs": {
            "geojson": str(geojson_path),
            "gpkg": str(gpkg_path),
        },
    }
    meta_path = write_meta(Path(args.out_dir), meta)

    LOG.info("GeoJSON: %s", geojson_path)
    LOG.info("GPKG: %s", gpkg_path)
    LOG.info("Meta: %s", meta_path)
    if warnings:
        for w in warnings:
            LOG.warning(w)
    LOG.info("完了: %d 件, 修正 %d 件", len(gdf), fix_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
