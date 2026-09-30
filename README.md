# Sentinel-3 water quality maps for 53 European perialpine lakes (2016–2025)

This dataset has satellite water quality maps for 53 lakes in and around the Alps, one NetCDF file per lake. Each file is a time series of maps, one map per Sentinel-3 overpass, from April 2016 to December 2025. There are four products:

- chlorophyll-a
- total suspended matter
- Secchi depth
- Forel-Ule colour index

The maps were made with [Sencast](https://github.com/eawag-surface-waters-research/sencast) from Sentinel-3 OLCI imagery. They are the same data shown on [Alplakes](https://www.alplakes.eawag.ch).

**Processing version:** Sencast commit [`3d581e8`](https://github.com/eawag-surface-waters-research/sencast/tree/3d581e8d546d9d691f6a62e9bc59dae1809f3d01) (`3d581e8d546d9d691f6a62e9bc59dae1809f3d01`), Docker image `0.2.0`.

This repository also contains the scripts that build the NetCDF files from the Sencast GeoTIFFs (see [Reproducing the dataset](#reproducing-the-dataset)).

## Quick start

```python
import xarray as xr

ds = xr.open_dataset("geneva.nc")

# Map of chlorophyll-a for one date
ds.chla_oc3.sel(time="2023-07-15", method="nearest").plot()

# Lake-wide median chlorophyll-a over time, only overpasses where at least 50% of the lake is valid.
# The grid is a bounding box that includes land, so measure coverage against the lake mask
# (pixels that are valid at least once), not against the whole grid.
lake_mask = ds.chla_oc3.notnull().any("time")
coverage = ds.chla_oc3.notnull().sum(["lat", "lon"]) / lake_mask.sum()
ds.chla_oc3.median(["lat", "lon"]).where(coverage > 0.5).plot()
```

## File structure

Each `{lake}.nc` file follows CF-1.8:

```
Dimensions:  time, lat, lon
Coordinates:
  time       (time)            acquisition time, UTC
  lat        (lat)             pixel centre latitude, degrees_north (decreasing, north to south)
  lon        (lon)             pixel centre longitude, degrees_east
  satellite  (time)            "S3A" or "S3B"
Variables:
  chla_oc3        (time, lat, lon) float32
  tsm_binding754  (time, lat, lon) float32
  secchi_lee      (time, lat, lon) float32
  forel_ule       (time, lat, lon) float32
  spatial_ref     ()               CRS definition (WGS 84, EPSG:4326)
Global attributes: title, lake, Conventions, source, sencast_commit, sencast_docker_image,
                   date_created, history, geospatial_lat_min/max, geospatial_lon_min/max,
                   time_coverage_start, time_coverage_end
```

- **Grid:** regular latitude/longitude grid in WGS 84. Pixels are about 0.0037° (longitude) × 0.0027° (latitude), roughly 300 m × 300 m, matching the OLCI full-resolution pixel. Each lake has its own grid, cropped to the lake.
- **Time:** one step per Sentinel-3 overpass that produced at least one product for the lake. Overpasses are between about 09:00 and 11:00 UTC. Sentinel-3A data start in 2016 and Sentinel-3B data in 2018. The `satellite` coordinate says which satellite each step came from.
- **Missing values:** `NaN` (`_FillValue = NaN`) marks pixels with no valid value, for example land, cloud or pixels removed by Sencast quality flags. Many time steps are mostly or entirely cloud-covered. Filter on the fraction of valid pixels before computing lake-wide statistics.
- **Compression:** zlib level 4, chunked as (up to 100 time steps, full lat, full lon).

## Variables

| Variable         | Description                                  | Units          | Sencast product                 | Typical range (Lake Geneva, 5th–95th percentile) |
|------------------|----------------------------------------------|----------------|---------------------------------|---------------------------|
| `chla_oc3`       | Chlorophyll-a concentration, OC3 algorithm   | mg m-3         | `OC3_chla`                      | 1.5 – 7.2                 |
| `tsm_binding754` | Total suspended matter, Binding 754 nm       | g m-3          | `COMBINE_tsm_binding754`        | 0.4 – 1.7                 |
| `secchi_lee`     | Secchi depth, Lee et al. algorithm           | m              | `SECCHIDEPTH_Zsd_lee`           | 3.9 – 10.1                |
| `forel_ule`      | Forel-Ule water colour index (integer 1–21)  | 1              | `FORELULE_forel_ule`            | 4 – 6                     |

Each variable's `source_product` attribute gives its Sencast product name, and `chla_oc3`, `tsm_binding754` and `secchi_lee` also have a CF `standard_name`. For algorithm details and validation, see the [Sencast documentation](https://github.com/eawag-surface-waters-research/sencast).

## Lakes

| File                | Time steps | Grid (lat × lon) | First      | Last       |
|---------------------|-----------:|------------------|------------|------------|
| `ageri.nc`          | 356  | 14 × 16   | 2016-04-29 | 2025-11-15 |
| `alpnachersee.nc`   | 282  | 12 × 15   | 2016-04-29 | 2025-10-21 |
| `ammersee.nc`       | 645  | 53 × 21   | 2016-04-10 | 2025-12-20 |
| `annecy.nc`         | 748  | 43 × 28   | 2016-04-25 | 2025-12-10 |
| `attersee.nc`       | 455  | 60 × 31   | 2016-04-30 | 2025-12-28 |
| `baldegg.nc`        | 106  | 15 × 10   | 2016-04-29 | 2025-06-29 |
| `biel.nc`           | 727  | 36 × 44   | 2016-04-14 | 2025-12-31 |
| `bled.nc`           | 113  | 5 × 8     | 2016-07-05 | 2025-12-15 |
| `bourget.nc`        | 769  | 59 × 22   | 2016-04-06 | 2025-12-10 |
| `brienz.nc`         | 855  | 27 × 45   | 2016-04-10 | 2025-12-31 |
| `caldonazzo.nc`     | 521  | 14 × 11   | 2016-04-10 | 2025-12-12 |
| `chiemsee.nc`       | 766  | 40 × 51   | 2016-04-10 | 2025-12-31 |
| `como.nc`           | 1038 | 133 × 88  | 2016-04-06 | 2025-12-30 |
| `constance.nc`      | 1174 | 127 × 243 | 2016-04-10 | 2025-12-31 |
| `garda.nc`          | 1328 | 166 × 100 | 2016-04-10 | 2025-12-31 |
| `geneva.nc`         | 1408 | 117 × 214 | 2016-04-06 | 2025-12-31 |
| `greifensee.nc`     | 329  | 20 × 16   | 2016-04-06 | 2025-11-15 |
| `hallstatter.nc`    | 333  | 26 × 13   | 2016-04-11 | 2025-11-12 |
| `hallwil.nc`        | 149  | 28 × 10   | 2016-05-18 | 2025-10-26 |
| `idro.nc`           | 596  | 29 × 21   | 2016-04-14 | 2025-12-27 |
| `iseo.nc`           | 846  | 62 × 42   | 2016-04-10 | 2025-12-30 |
| `joux.nc`           | 273  | 21 × 25   | 2016-05-06 | 2025-11-07 |
| `kochelsee.nc`      | 483  | 12 × 14   | 2016-04-21 | 2025-11-12 |
| `lucerne.nc`        | 808  | 72 × 87   | 2016-04-29 | 2025-12-18 |
| `lugano.nc`         | 866  | 50 × 72   | 2016-04-06 | 2025-12-30 |
| `maggiore.nc`       | 1098 | 170 × 104 | 2016-04-06 | 2025-12-31 |
| `millstaetter.nc`   | 608  | 20 × 38   | 2016-04-10 | 2025-12-19 |
| `mondsee.nc`        | 515  | 21 × 31   | 2016-04-11 | 2025-11-14 |
| `murten.nc`         | 610  | 20 × 28   | 2016-04-06 | 2025-12-31 |
| `neuchatel.nc`      | 946  | 84 × 113  | 2016-04-06 | 2025-12-31 |
| `obertrumer.nc`     | 60   | 16 × 11   | 2016-12-09 | 2025-12-20 |
| `ossiacher.nc`      | 439  | 18 × 35   | 2016-04-11 | 2025-11-14 |
| `pfaffikon.nc`      | 149  | 10 × 8    | 2016-05-22 | 2025-10-07 |
| `sarnen.nc`         | 367  | 17 × 16   | 2016-04-29 | 2025-11-15 |
| `sempach.nc`        | 391  | 21 × 20   | 2016-04-06 | 2025-11-15 |
| `sihlsee.nc`        | 394  | 27 × 18   | 2016-04-10 | 2025-10-29 |
| `sils.nc`           | 258  | 11 × 14   | 2016-05-22 | 2025-10-12 |
| `silvaplana.nc`     | 338  | 9 × 9     | 2016-04-21 | 2025-11-18 |
| `simssee.nc`        | 101  | 16 × 16   | 2016-04-29 | 2025-11-04 |
| `starnberger.nc`    | 533  | 67 × 25   | 2016-04-10 | 2025-11-15 |
| `tegernsee.nc`      | 374  | 22 × 15   | 2016-04-29 | 2025-11-12 |
| `thun.nc`           | 855  | 35 × 55   | 2016-04-10 | 2025-12-31 |
| `traunsee.nc`       | 411  | 41 × 14   | 2016-04-22 | 2025-10-14 |
| `waegitaler.nc`     | 265  | 16 × 9    | 2016-04-10 | 2025-11-05 |
| `walchensee.nc`     | 619  | 19 × 25   | 2016-04-29 | 2025-12-27 |
| `walensee.nc`       | 644  | 11 × 56   | 2016-04-10 | 2025-12-31 |
| `wallersee.nc`      | 66   | 12 × 19   | 2016-04-30 | 2025-09-21 |
| `wolfgangsee.nc`    | 498  | 23 × 32   | 2016-04-11 | 2025-11-14 |
| `worthersee.nc`     | 542  | 12 × 58   | 2016-04-10 | 2025-11-11 |
| `worthsee.nc`       | 208  | 12 × 11   | 2016-04-10 | 2025-09-18 |
| `zeller.nc`         | 340  | 14 × 8    | 2016-04-11 | 2025-11-08 |
| `zug.nc`            | 534  | 45 × 21   | 2016-04-29 | 2025-11-15 |
| `zurich.nc`         | 754  | 66 × 112  | 2016-04-10 | 2025-11-15 |

The whole dataset is about 185 MB. To regenerate this table and the total size after a rebuild, run `python scripts/lake_table.py`.

## Limitations

- **Small lakes:** at about 300 m resolution, small lakes (e.g. Bled, Pfäffikon, Silvaplana) are only a few pixels across. Pixels near the shore can be affected by adjacency effects from land.
- **Clouds:** coverage is uneven. Winter and cloudy periods have far fewer valid observations, and the number of time steps varies a lot between lakes.
- **Estimates, not measurements:** all products come from the satellite signal using general algorithms, not lake-specific ones. Absolute values should be checked against in-situ data before quantitative use.

## Reproducing the dataset

The NetCDF files are built from the per-scene Sencast GeoTIFFs in `s3://eawagrs/alplakes/cropped/sentinel3/{lake}/`. These were produced with Sencast commit `3d581e8d546d9d691f6a62e9bc59dae1809f3d01` (Docker image `0.2.0`). If you change Sencast versions, update `SENCAST_COMMIT` and `SENCAST_DOCKER_IMAGE` in `scripts/functions.py`. The GeoTIFF filenames follow `{PROCESSOR}_{param}_{S3A|S3B}_{YYYYMMDDTHHMMSS}_{lake}.tif`. Only the products listed in `PRODUCTS` in `scripts/functions.py` are downloaded and converted; any other GeoTIFFs in the input folder are ignored.

Requirements:

- the conda environment in `environment.yml` (GDAL, numpy, pandas, xarray, netCDF4, AWS CLI, plus matplotlib and JupyterLab for the notebook):
  ```bash
  conda env create -f environment.yml
  conda activate sencast-publish
  ```
- read access to `s3://eawagrs` for the AWS CLI

Run from the repository root:

```bash
# Download GeoTIFFs up to the end of 2025, delete local files outside that range, rebuild all NetCDFs
python scripts/main.py --sync --start 2016-01-01 --end 2025-12-31 --overwrite

# Build NetCDFs from GeoTIFFs already in data/tiff/sentinel3
python scripts/main.py

# Only some lakes
python scripts/main.py --sync --lakes walensee zug --overwrite
```

| Option        | Default                                      | Description |
|---------------|----------------------------------------------|-------------|
| `--input`     | `data/tiff/sentinel3`                        | GeoTIFF folder |
| `--output`    | `data/netcdf/sentinel3`                      | NetCDF folder |
| `--lakes`     | all                                          | Only process these lakes |
| `--overwrite` | off                                          | Rebuild existing NetCDFs (otherwise they are skipped) |
| `--workers`   | CPU count                                    | Parallel worker processes |
| `--sync`      | off                                          | Download GeoTIFFs from `--bucket` with `aws s3 sync` before processing |
| `--bucket`    | `s3://eawagrs/alplakes/cropped/sentinel3/`   | Where to download from |
| `--start`     | none                                         | First date to keep (inclusive) |
| `--end`       | none                                         | Last date to keep (inclusive) |

With `--start` or `--end` set, **local GeoTIFFs outside the range are deleted** (only for the lakes given with `--lakes`, if set). `--sync` only downloads the years in that range. Use `--overwrite` together with dates so that existing NetCDFs are rebuilt with the new time range.

Each lake is written to `{lake}.nc.tmp` and renamed when complete, so a failed run never leaves a partial NetCDF. If any lake fails, the script exits with status 1. Within a lake, GeoTIFFs whose grid differs from the lake's most common grid are skipped with a warning, and GeoTIFF nodata values become `NaN`.

Run the tests from the repository root with `pytest`.

Repository layout:

```
scripts/main.py        command-line entry point
scripts/functions.py   S3 download, date filtering, GeoTIFF → NetCDF conversion
scripts/lake_table.py  prints the lakes table above from the NetCDFs
tests/                 pytest tests for scripts/functions.py
notebooks/             exploration of the output NetCDFs
environment.yml        conda environment
data/                  downloaded and generated data (git-ignored)
```

## Citation and license

<!-- TODO: add DOI, recommended citation, data license (e.g. CC BY 4.0) and contact before publishing -->

The code in this repository is released under the [MIT License](LICENSE).

Contains modified Copernicus Sentinel data (2016–2025), processed by Eawag with Sencast.
