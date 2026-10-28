"""Helpers for syncing Sencast GeoTIFFs from S3 and combining them into per-lake NetCDFs."""
import collections
import glob
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import xarray as xr
from osgeo import gdal

gdal.UseExceptions()
gdal.PushErrorHandler("CPLQuietErrorHandler")  # silence PROJ db warnings from the sencast env; errors still raise
log = logging.getLogger("tiff_to_netcdf")

# Sencast version that produced the input GeoTIFFs, recorded in the NetCDF attributes.
# Check the commit hashes recorded per scene in the Alplakes metadata (s3://eawagrs/alplakes/metadata/{sensor}/{lake}/{param}.json, key "c").
SENCAST_COMMIT = "d797620940c82a8046b95f1ab268199ef9314350"
SENCAST_DOCKER_IMAGE = "0.2.0"

# {PRODUCT}_{param}_{platform}_{YYYYMMDDTHHMMSS}[_{MGRS tile}]_{lake}[_lowres].tif
FILENAME = re.compile(
    r"^(?P<product>[A-Z0-9]+_[A-Za-z0-9_]+?)_(?P<sat>S\d[A-Z])_(?P<time>\d{8}T\d{6})"
    r"(?:_(?P<tile>T\d{2}[A-Z]{3}))?_(?P<lake>[A-Za-z0-9_-]+?)(?P<lowres>_lowres)?\.tif$"
)

# sensor -> display name and products; products map Sencast product -> (variable name, attributes).
# A new sensor is added here; its data lives in data/{tiff,netcdf}/{sensor} and the bucket's {sensor}/ prefix.
SENSORS = {
    "sentinel3": {
        "name": "Sentinel-3 OLCI",
        "products": {
            "OC3_chla": ("chla_oc3", {
                "long_name": "Chlorophyll-a concentration (OC3)",
                "standard_name": "mass_concentration_of_chlorophyll_a_in_sea_water",
                "units": "mg m-3"}),
            "COMBINE_tsm_binding754": ("tsm_binding754", {
                "long_name": "Total suspended matter (Binding 754)",
                "standard_name": "mass_concentration_of_suspended_matter_in_sea_water",
                "units": "g m-3"}),
            "SECCHIDEPTH_Zsd_lee": ("secchi_lee", {
                "long_name": "Secchi depth (Lee)",
                "standard_name": "secchi_depth_of_sea_water",
                "units": "m"}),
            "FORELULE_forel_ule": ("forel_ule", {"long_name": "Forel-Ule colour index", "units": "1"}),
        },
        # Lakes left out of the output because their data is too sparse to be useful.
        "exclude": ["baldegg", "bled", "simssee"],
    },
}


def in_window(t, start=None, end=None):
    """True if timestamp t falls within [start, end]; dates are inclusive of the whole end day."""
    if start is not None and t < start.normalize():
        return False
    if end is not None and t >= end.normalize() + pd.Timedelta(days=1):
        return False
    return True


def list_lakes(source):
    """Return the lake folders directly under an S3 prefix."""
    out = subprocess.run(["aws", "s3", "ls", source.rstrip("/") + "/"], capture_output=True, text=True, check=True).stdout
    return [line.split()[-1].rstrip("/") for line in out.splitlines() if line.strip().startswith("PRE ")]


def sync_bucket(source, dest, products, lakes=None, start=None, end=None, workers=8):
    """Mirror GeoTIFFs from an S3 prefix into dest/{lake}/ using one `aws s3 sync` per lake.

    Only the given products are downloaded (which also leaves out Sencast's temp_*.tif and _lowres files),
    and only years overlapping [start, end]; day-level trimming is left to prune_files.
    Syncing per lake keeps each listing small; patterns are relative to the lake folder.
    """
    source = source.rstrip("/") + "/"
    if start is not None or end is not None:
        first = (start or pd.Timestamp("2016-01-01")).year
        last = (end or pd.Timestamp.now()).year
        years = [str(year) for year in range(first, last + 1)]
    else:
        years = [""]
    patterns = [f"{product}_S??_{year}*.tif" for product in products for year in years]
    filters = ["--exclude", "*"] + [arg for p in patterns for arg in ("--include", p)] + ["--exclude", "*_lowres.tif"]

    def sync(lake):
        dst = os.path.join(dest, lake)
        os.makedirs(dst, exist_ok=True)
        subprocess.run(["aws", "s3", "sync", source + f"{lake}/", dst, "--only-show-errors", *filters], check=True)

    lakes = lakes or list_lakes(source)
    log.info("Syncing %d lakes from %s", len(lakes), source)
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(sync, lake): lake for lake in lakes}
        for fut in as_completed(futures):
            try:
                fut.result()
                log.info("%s: synced", futures[fut])
            except subprocess.CalledProcessError:
                log.exception("%s: sync failed", futures[fut])
                failed.append(futures[fut])
    if failed:
        raise RuntimeError(f"Sync failed for {len(failed)} lakes: {', '.join(sorted(failed))}")


def prune_files(root, start=None, end=None, lakes=None):
    """Delete GeoTIFFs under root/{lake}/ whose acquisition time is outside [start, end].

    If lakes is given, only those lakes' folders are touched.
    """
    removed = 0
    for lake in lakes or ["*"]:
        for path in glob.glob(os.path.join(root, lake, "*.tif")):
            m = FILENAME.match(os.path.basename(path))
            if m and not in_window(pd.Timestamp(m["time"]), start, end):
                os.remove(path)
                removed += 1
    log.info("Removed %d files outside the time window", removed)


def index_files(root, products):
    """Return {lake: [(product, sat, time, path), ...]}, skipping unrecognised, unwanted and _lowres files."""
    lakes = collections.defaultdict(list)
    skipped = 0
    for path in sorted(glob.glob(os.path.join(root, "*", "*.tif"))):
        m = FILENAME.match(os.path.basename(path))
        if not m or m["product"] not in products or m["lowres"]:
            skipped += 1
            log.debug("Skipping %s", path)
            continue
        lakes[m["lake"]].append((m["product"], m["sat"], pd.Timestamp(m["time"]), path))
    log.info("Indexed %d files across %d lakes (%d skipped)", sum(map(len, lakes.values())), len(lakes), skipped)
    return lakes


def grid_of(ds):
    # Compare raw WKT rather than going through PROJ (the sencast env's proj.db is missing)
    return ds.RasterXSize, ds.RasterYSize, ds.GetGeoTransform(), ds.GetProjection()


def read_band(path):
    """Read band 1 as float32 with the nodata value (if any) replaced by NaN."""
    ds = gdal.Open(path)  # keep a reference: the band is invalid once the dataset is freed
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    if nodata is not None and not np.isnan(nodata):
        arr[arr == np.float32(nodata)] = np.nan
    return arr


def build_lake(lake, files, out_path, sensor):
    """Write one NetCDF for a lake from its GeoTIFFs; returns (lake, n_times, valid scenes per variable).

    sensor is an entry of SENSORS (display name and products).

    The lake's grid is the most common one among its files; files on any other grid are skipped.
    Products are written one at a time so only one (time, lat, lon) array is held in memory.
    """
    grids = {}
    for f in files:
        ds = gdal.Open(f[3])
        grids[f[3]] = grid_of(ds)
        ds = None
    ref_grid, _ = collections.Counter(grids.values()).most_common(1)[0]
    mismatched = [f for f in files if grids[f[3]] != ref_grid]
    for f in mismatched:
        log.warning("%s: grid mismatch, skipping %s", lake, f[3])
    files = [f for f in files if grids[f[3]] == ref_grid]

    nx, ny, gt, wkt = ref_grid
    lon = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    lat = gt[3] + (np.arange(ny) + 0.5) * gt[5]

    # Union of acquisition times; each time belongs to one satellite
    sat_by_time = {}
    for _, sat, t, _ in files:
        sat_by_time[t] = sat
    times = sorted(sat_by_time)
    tidx = {t: i for i, t in enumerate(times)}
    by_product = collections.defaultdict(list)
    for product, _, t, path in files:
        by_product[product].append((tidx[t], path))

    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    coords = {
        "time": ("time", pd.DatetimeIndex(times), {"standard_name": "time", "long_name": "acquisition time", "axis": "T"}),
        "lat": ("lat", lat, {"standard_name": "latitude", "units": "degrees_north", "axis": "Y"}),
        "lon": ("lon", lon, {"standard_name": "longitude", "units": "degrees_east", "axis": "X"}),
        "satellite": ("time", np.array([sat_by_time[t] for t in times]), {"long_name": "Satellite platform"}),
    }
    base = xr.Dataset({"spatial_ref": ((), np.int32(0), {
        "crs_wkt": wkt,
        "grid_mapping_name": "latitude_longitude",
        "semi_major_axis": 6378137.0,
        "inverse_flattening": 298.257223563,
    })}, coords=coords, attrs={
        "title": f"Sencast {sensor['name']} water quality products for {lake}",
        "lake": lake,
        "Conventions": "CF-1.8",
        "source": f"{sensor['name']} processed with Sencast (https://github.com/eawag-surface-waters-research/sencast)",
        "sencast_commit": SENCAST_COMMIT,
        "sencast_docker_image": SENCAST_DOCKER_IMAGE,
        "date_created": now,
        "history": f"{now}: created from {len(files)} GeoTIFFs by scripts/main.py",
        # Pixel edges, not centres
        "geospatial_lat_min": float(min(gt[3], gt[3] + ny * gt[5])),
        "geospatial_lat_max": float(max(gt[3], gt[3] + ny * gt[5])),
        "geospatial_lon_min": float(min(gt[0], gt[0] + nx * gt[1])),
        "geospatial_lon_max": float(max(gt[0], gt[0] + nx * gt[1])),
        "time_coverage_start": times[0].isoformat(),
        "time_coverage_end": times[-1].isoformat(),
    })
    chunks = (min(100, len(times)), ny, nx)

    tmp = out_path + ".tmp"
    counts = {}
    try:
        base.to_netcdf(tmp, encoding={
            "time": {"units": "seconds since 1970-01-01", "dtype": "int64"},
            "lat": {"_FillValue": None},
            "lon": {"_FillValue": None},
        })
        for product in sorted(by_product):
            name, attrs = sensor["products"][product]
            arr = np.full((len(times), ny, nx), np.nan, dtype=np.float32)
            for i, path in by_product[product]:
                arr[i] = read_band(path)
            var = xr.Dataset({name: (("time", "lat", "lon"), arr, {
                **attrs, "source_product": product, "grid_mapping": "spatial_ref", "coordinates": "satellite"})})
            var.to_netcdf(tmp, mode="a", encoding={name: {
                "zlib": True, "complevel": 4, "chunksizes": chunks, "_FillValue": np.float32(np.nan)}})
            counts[name] = int(np.isfinite(arr).any(axis=(1, 2)).sum())
            del arr, var
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return lake, len(times), counts
