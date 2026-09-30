"""Combine per-scene Sencast GeoTIFFs into one NetCDF per lake.

Input:  data/tiff/sentinel3/{lake}/{PROCESSOR}_{param}_{S3A|S3B}_{YYYYMMDDTHHMMSS}_{lake}.tif
Output: data/netcdf/sentinel3/{lake}.nc with dims (time, lat, lon) and one variable per product.

Optionally syncs the input GeoTIFFs from S3 first, and deletes local GeoTIFFs outside --start/--end.
Exits with status 1 if any lake fails.

Usage:
    python main.py                                          # all lakes
    python main.py --lakes walensee zug --overwrite
    python main.py --sync --start 2023-01-01 --end 2023-12-31 --overwrite
"""
import argparse
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from functions import build_lake, index_files, log, prune_files, sync_bucket


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="data/tiff/sentinel3")
    parser.add_argument("--output", default="data/netcdf/sentinel3")
    parser.add_argument("--lakes", nargs="*", help="Only process these lakes")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--sync", action="store_true", help="Download GeoTIFFs from --bucket before processing")
    parser.add_argument("--bucket", default="s3://eawagrs/alplakes/cropped/sentinel3/")
    parser.add_argument("--start", type=pd.Timestamp, help="First date to keep (inclusive), e.g. 2023-01-01")
    parser.add_argument("--end", type=pd.Timestamp, help="Last date to keep (inclusive), e.g. 2023-12-31")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.sync:
        sync_bucket(args.bucket, args.input, args.lakes, args.start, args.end)
    if args.start is not None or args.end is not None:
        prune_files(args.input, args.start, args.end, args.lakes)

    lakes = index_files(args.input)
    if args.lakes:
        for lake in sorted(set(args.lakes) - set(lakes)):
            log.warning("%s: no GeoTIFFs found in %s", lake, args.input)
        lakes = {k: v for k, v in lakes.items() if k in args.lakes}
    os.makedirs(args.output, exist_ok=True)

    jobs = {}
    failed = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for lake, files in sorted(lakes.items()):
            out_path = os.path.join(args.output, f"{lake}.nc")
            if os.path.exists(out_path) and not args.overwrite:
                log.info("%s: exists, skipping", lake)
                continue
            jobs[pool.submit(build_lake, lake, files, out_path)] = lake
        for fut in as_completed(jobs):
            try:
                lake, nt, counts = fut.result()
                log.info("%s: %d times, %s", lake, nt, counts)
            except Exception:
                log.exception("%s: failed", jobs[fut])
                failed.append(jobs[fut])

    if failed:
        log.error("%d of %d lakes failed: %s", len(failed), len(jobs), ", ".join(sorted(failed)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
