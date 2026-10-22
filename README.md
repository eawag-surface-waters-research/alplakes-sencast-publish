# alplakes-sencast-publish

Scripts that turn per-scene [Sencast](https://github.com/eawag-surface-waters-research/sencast) GeoTIFFs into one CF-compliant NetCDF time series per lake, ready for publishing.

Published datasets and their documentation are listed under [Releases](#releases).

## What the processing does

For one sensor (e.g. `sentinel3`), `scripts/main.py` runs these steps:

1. **Sync** (optional, `--sync`): downloads the GeoTIFFs from `s3://eawagrs/alplakes/cropped/{sensor}/{lake}/` into `data/tiff/{sensor}/{lake}/`.
   - It runs one `aws s3 sync` per lake, 8 in parallel.
   - Only the sensor's configured products are fetched, and only the years within `--start`/`--end`.
   - Files already present with the same size and timestamp are skipped.
2. **Prune** (when `--start`/`--end` are given): deletes local GeoTIFFs whose acquisition time is outside the window. Both dates are inclusive.
3. **Index:** parses every GeoTIFF filename and groups the files by lake. It ignores files that are:
   - not one of the configured products
   - `_lowres` copies
   - Sencast `temp_*` leftovers
4. **Build:** writes `data/netcdf/{sensor}/{lake}.nc`, one lake per worker process. For each lake:
   - The lake grid is the most common grid among its GeoTIFFs. Files on another grid are skipped with a warning.
   - The time axis is the union of all acquisition times. A product missing at a given time is all `NaN`.
   - GeoTIFF nodata values become `NaN`.
   - Each product is written as a float32 `(time, lat, lon)` variable, compressed with zlib level 4 and chunked in blocks of up to 100 time steps.
   - The file is written to `{lake}.nc.tmp` and renamed when complete, so a failed run never leaves a partial NetCDF. If any lake fails, the script exits with status 1.

### Input filenames

```
{PRODUCT}_{param}_{platform}_{YYYYMMDDTHHMMSS}[_{MGRS tile}]_{lake}[_lowres].tif
e.g. OC3_chla_S3A_20160429T100135_ageri.tif
```

### Output format

Each `{lake}.nc` follows CF-1.8:
- **Coordinates:**
  - `time` (UTC)
  - `lat`/`lon` (pixel centres, WGS 84)
  - `satellite` along `time` (e.g. `S3A`)
- **Variables:** one per configured product. Each has `long_name`, `units` and, where one exists, a CF `standard_name`. A `source_product` attribute gives the Sencast product name.
- **`spatial_ref`:** a CF grid-mapping variable holding the CRS (WKT), which GIS tools such as QGIS, GDAL and rioxarray read.
- **Global attributes:**
  - `title`, `lake`, `source`
  - `sencast_commit`, `sencast_docker_image`
  - `date_created`, `history`
  - the geospatial bounds and time coverage

### Sensors and products

Sensors are configured in `SENSORS` in [`scripts/functions.py`](scripts/functions.py). Each entry has a display name and maps Sencast product names to NetCDF variable names and attributes. A sensor's data lives under `data/tiff/{sensor}`, `data/netcdf/{sensor}` and `s3://eawagrs/alplakes/cropped/{sensor}/`.

| Sensor      | Products → variables |
|-------------|----------------------|
| `sentinel3` | `OC3_chla` → `chla_oc3`, `COMBINE_tsm_binding754` → `tsm_binding754`, `SECCHIDEPTH_Zsd_lee` → `secchi_lee`, `FORELULE_forel_ule` → `forel_ule` |

To add a sensor, add an entry to `SENSORS` and run with `--sensor <name>`. Note that the build currently assumes one grid per lake. Inputs split over several tiles, such as Sentinel-2 MGRS tiles, would need mosaicking first.

The Sencast version that produced the input GeoTIFFs is recorded in every NetCDF. It is set by `SENCAST_COMMIT` and `SENCAST_DOCKER_IMAGE` in `scripts/functions.py`; update these when the inputs are reprocessed with a different Sencast version.

## Requirements

- The conda environment in `environment.yml`:
  ```bash
  conda env create -f environment.yml
  conda activate sencast-publish
  ```
  It contains GDAL, numpy, pandas, xarray, netCDF4, the AWS CLI and pytest, plus matplotlib and JupyterLab for the notebook.

  To reproduce a release exactly, use that release's lock file in `releases/` instead. It lists the exact package versions used to build the published data (Linux 64-bit):
  ```bash
  conda create -n sencast-publish --file releases/sentinel3_2016-2025.lock.txt
  ```
- Read access to `s3://eawagrs` for the AWS CLI (only needed for `--sync`).

## Usage

Run from the repository root:

```bash
# Download GeoTIFFs up to the end of 2025, delete local files after that, rebuild all NetCDFs
python scripts/main.py --sync --end 2025-12-31 --overwrite

# Build NetCDFs from GeoTIFFs already in data/tiff/sentinel3
python scripts/main.py

# Only some lakes
python scripts/main.py --sync --lakes walensee zug --overwrite
```

| Option        | Default                                      | Description |
|---------------|----------------------------------------------|-------------|
| `--sensor`    | `sentinel3`                                  | Sensor to process (an entry in `SENSORS`) |
| `--input`     | `data/tiff/{sensor}`                         | GeoTIFF folder |
| `--output`    | `data/netcdf/{sensor}`                       | NetCDF folder |
| `--lakes`     | all                                          | Only process these lakes |
| `--overwrite` | off                                          | Rebuild existing NetCDFs (otherwise they are skipped) |
| `--workers`   | CPU count                                    | Parallel worker processes for the build |
| `--sync`      | off                                          | Download GeoTIFFs from `--bucket` before processing |
| `--bucket`    | `s3://eawagrs/alplakes/cropped/{sensor}/`    | Where to download from |
| `--start`     | none                                         | First date to keep (inclusive) |
| `--end`       | none                                         | Last date to keep (inclusive) |

**`--start` and `--end` delete local GeoTIFFs outside the range.** Only the lakes given with `--lakes` are affected, if it is set. Running `--sync` later without dates downloads the deleted files again. Use `--overwrite` together with dates so that existing NetCDFs are rebuilt with the new time range.

## Tests

```bash
pytest
```

## Releases

Each published dataset has a release file and a lock file in [`releases/`](releases/):
- `{release}.md` describes the data, including coverage, variables, lakes, limitations and contacts, and records the Sencast version and the command used to produce it. Upload this file alongside the NetCDFs as `README.md`.
- `{release}.lock.txt` lists the exact conda packages used to build it.

| Release | Sensor | Period | Lakes | DOI |
|---------|--------|--------|------:|-----|
| [sentinel3_2016-2025](releases/sentinel3_2016-2025.md) | Sentinel-3 OLCI | 2016-04 – 2025-12 | 53 | pending |

To make a new release:
1. Build the NetCDFs, then save the environment used as the release's lock file (`conda list -n <env> --explicit > releases/<release>.lock.txt`).
2. Copy the latest release file, then update its coverage, lake table, versions and Sencast parameter file. Always link the parameter file at the pinned Sencast commit, not `master`.
3. Commit, then tag the commit of this repository that was used.
4. Publish on [ERIC](https://scientific-it.eawag.ch/services/rdm/publish/) and add the DOI to the table above.

## Repository layout

```
scripts/main.py        command-line entry point
scripts/functions.py   sensor config, S3 sync, date filtering, GeoTIFF → NetCDF conversion
tests/                 pytest tests for scripts/functions.py
notebooks/             exploration of the output NetCDFs
releases/              documentation and conda lock file for each published dataset
environment.yml        conda environment
data/                  downloaded and generated data (git-ignored)
```

## License

The code in this repository is released under the [MIT License](LICENSE). Data licenses are given in each release file.
