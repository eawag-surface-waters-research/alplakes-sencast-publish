"""Tests for scripts/functions.py. Run from the repository root with `pytest`."""
import os
import sys

import numpy as np
import pandas as pd
import pytest
import xarray as xr

gdal = pytest.importorskip("osgeo.gdal")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import functions as F  # noqa: E402

GT = (6.0, 0.01, 0, 46.5, 0, -0.01)


def write_tif(path, arr, gt=GT, nodata=None):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    ds.SetProjection('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                     'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]')
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    ds = None
    return str(path)


def test_filename_regex():
    m = F.FILENAME.match("COMBINE_tsm_binding754_S3B_20250528T095312_como.tif")
    assert (m["product"], m["sat"], m["time"], m["lake"]) == ("COMBINE_tsm_binding754", "S3B", "20250528T095312", "como")
    assert F.FILENAME.match("OC3_chla_S3A_20160429T100135_lake_with_underscores.tif")["lake"] == "lake_with_underscores"
    # Sencast leftovers must not be picked up
    assert F.FILENAME.match("temp_OC3_chla_S3B_20250528T095312_como.tif") is None


def test_in_window():
    start, end = pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")
    assert F.in_window(pd.Timestamp("2023-01-01T00:00:00"), start, end)
    assert F.in_window(pd.Timestamp("2023-12-31T23:59:59"), start, end)
    assert not F.in_window(pd.Timestamp("2022-12-31T23:59:59"), start, end)
    assert not F.in_window(pd.Timestamp("2024-01-01T00:00:00"), start, end)
    assert F.in_window(pd.Timestamp("1990-01-01"))


def test_prune_files_only_touches_given_lakes(tmp_path):
    for lake in ("a", "b"):
        (tmp_path / lake).mkdir()
        for t in ("20200101T100000", "20230101T100000"):
            (tmp_path / lake / f"OC3_chla_S3A_{t}_{lake}.tif").touch()
    F.prune_files(str(tmp_path), start=pd.Timestamp("2021-01-01"), lakes=["a"])
    assert sorted(os.listdir(tmp_path / "a")) == ["OC3_chla_S3A_20230101T100000_a.tif"]
    assert len(os.listdir(tmp_path / "b")) == 2


def test_build_lake(tmp_path):
    a = np.arange(6, dtype=np.float32).reshape(2, 3)
    b = a.copy()
    b[0, 0] = -9999
    t1, t2, t3 = pd.Timestamp("2020-01-01T10:00"), pd.Timestamp("2020-01-02T10:00"), pd.Timestamp("2020-01-03T10:00")
    files = [
        # Odd grid listed first: the most common grid must still win
        ("FORELULE_forel_ule", "S3A", t2, write_tif(tmp_path / "odd.tif", np.zeros((4, 4), np.float32), (0, 1, 0, 0, 0, -1))),
        ("OC3_chla", "S3A", t1, write_tif(tmp_path / "c1.tif", a)),
        ("OC3_chla", "S3B", t3, write_tif(tmp_path / "c3.tif", b, nodata=-9999)),
        ("COMBINE_tsm_binding754", "S3A", t1, write_tif(tmp_path / "t1.tif", a * 2)),
    ]
    out = tmp_path / "x.nc"
    lake, nt, counts = F.build_lake("x", files, str(out))

    assert (lake, nt, counts) == ("x", 2, {"chla_oc3": 2, "tsm_binding754": 1})
    assert not os.path.exists(str(out) + ".tmp")
    with xr.open_dataset(out) as ds:
        assert list(ds.time.values) == [np.datetime64(t1), np.datetime64(t3)]
        assert list(ds.satellite.values) == ["S3A", "S3B"]
        np.testing.assert_allclose(ds.lat, [46.495, 46.485])
        np.testing.assert_allclose(ds.lon, [6.005, 6.015, 6.025])
        np.testing.assert_array_equal(ds.chla_oc3[0], a)
        assert np.isnan(ds.chla_oc3[1, 0, 0])  # nodata -> NaN
        assert np.isnan(ds.tsm_binding754[1]).all()  # no TSM at t3
        assert "forel_ule" not in ds
        assert ds.attrs["sencast_commit"] == F.SENCAST_COMMIT
