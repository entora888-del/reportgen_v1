from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from tools.build_50k_index import (
    build_polygons,
    enrich_attributes,
    load_source,
    to_wgs84,
    validate_and_fix,
)


def _write_sample_csv(tmp_path: Path) -> Path:
    csv_text = """code,name_ja,lat_ul,lon_ul,lat_ur,lon_ur,lat_lr,lon_lr,lat_ll,lon_ll
2806,北条,35.0,134.9,35.0,135.0,34.9,135.0,34.9,134.9
2807,社,34.9,134.9,34.9,135.0,34.8,135.0,34.8,134.9
"""
    path = tmp_path / "sample50k.csv"
    path.write_text(csv_text, encoding="utf-8")
    return path


def test_build_polygons_from_corners(tmp_path):
    csv_path = _write_sample_csv(tmp_path)
    result = load_source(csv_path, "csv", layer=None)
    assert result.mode == "corners"
    df = to_wgs84(result.data, result.mode, datum="wgs84")
    gdf = build_polygons(df, result.mode)
    gdf = enrich_attributes(gdf, "テスト出典", "https://example.com", "2024-01-01T00:00:00Z")
    validated, fix_count, warnings = validate_and_fix(gdf)
    assert len(validated) == 2
    assert fix_count == 0
    assert isinstance(warnings, list)


def test_tokyo_datum_conversion_changes_coordinates():
    df = pd.DataFrame(
        {
            "code": ["1001"],
            "name_ja": ["サンプル"],
            "lat_ul": [35.0],
            "lon_ul": [135.0],
            "lat_ur": [35.0],
            "lon_ur": [135.1],
            "lat_lr": [34.9],
            "lon_lr": [135.1],
            "lat_ll": [34.9],
            "lon_ll": [135.0],
        }
    )
    converted = to_wgs84(df, mode="corners", datum="tokyo")
    assert float(converted.loc[0, "lat_ul"]) != pytest.approx(35.0)
    assert float(converted.loc[0, "lon_ul"]) != pytest.approx(135.0)


def test_validate_and_fix_rejects_zero_area():
    df = pd.DataFrame(
        {
            "code": ["9999"],
            "name_ja": ["ゼロ"],
            "lat_ul": [35.0],
            "lon_ul": [135.0],
            "lat_ur": [35.0],
            "lon_ur": [135.0],
            "lat_lr": [35.0],
            "lon_lr": [135.0],
            "lat_ll": [35.0],
            "lon_ll": [135.0],
        }
    )
    gdf = build_polygons(df, mode="corners")
    gdf = enrich_attributes(gdf, "出典", "https://example.com", "2024-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        validate_and_fix(gdf)
