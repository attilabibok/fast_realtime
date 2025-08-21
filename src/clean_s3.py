#!/usr/bin/env python3
import asyncio
import itertools
import logging
from typing import List

import argparse

# Import your existing helpers
# from your_module import S3APISettings, get_session
# If they live alongside this script, just ensure the imports resolve.

from utils import S3APISettings
from aiobotocore.session import get_session

logger = logging.getLogger("s3-delete-esrijson")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

SUFFIX_DEFAULT = "esrijson.json"
BUCKET_DEFAULT = "knatempstorage"
PREFIX_DEFAULT = "fast_historic/"
DRY_RUN = False

def chunked(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            return
        yield chunk

async def list_matching_keys(s3, bucket: str, prefix: str, suffix: str) -> List[str]:
    """
    Use aiobotocore paginator to list keys under prefix that end with suffix.
    """
    paginator = s3.get_paginator("list_objects_v2")
    matched = []

    async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if key.endswith(suffix):
                matched.append(key)
    return matched

async def delete_keys_batched(s3, bucket: str, keys: List[str]) -> int:
    """
    Delete keys in batches of up to 1000 (S3 limit for DeleteObjects).
    Returns total deleted count (best-effort).
    """
    deleted_total = 0
    for batch in chunked(keys, 1000):
        resp = await s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        deleted = len(resp.get("Deleted", []))
        errors = resp.get("Errors", [])
        deleted_total += deleted

        if errors:
            for e in errors:
                logger.warning("Delete error for %s: %s %s", e.get("Key"), e.get("Code"), e.get("Message"))
    return deleted_total

async def run(bucket: str, prefix: str, suffix: str, dry_run: bool):
    s3settings = S3APISettings()
    session = get_session()

    # Fallback region to us-east-1 if your settings doesn't carry one
    region = getattr(s3settings, "region_name", "us-east-1")

    async with session.create_client(
        "s3",
        region_name=region,
        aws_access_key_id=s3settings.access_key_id,
        aws_secret_access_key=s3settings.secret_access_key,
    ) as s3:
        logger.info("Scanning s3://%s/%s for *%s ...", bucket, prefix, suffix)
        keys = await list_matching_keys(s3, bucket, prefix, suffix)

        if not keys:
            logger.info("No matching objects found.")
            return

        logger.info("Found %d matching object(s).", len(keys))
        for k in keys:
            logger.info("  %s", k)

        if dry_run:
            logger.info("Dry-run: no deletions performed. Re-run with --no-dry-run to delete.")
            return

        deleted = await delete_keys_batched(s3, bucket, keys)
        logger.info("Deleted %d object(s).", deleted)

def main():
    parser = argparse.ArgumentParser(description="Delete *esrijson.json files from an S3 bucket subfolder (async).")
    parser.add_argument("--bucket", required=False, help="S3 bucket name", default=BUCKET_DEFAULT)
    parser.add_argument("--prefix", required=False, help="S3 prefix (subfolder), e.g., path/to/subfolder/", default=PREFIX_DEFAULT)
    parser.add_argument("--suffix", default=SUFFIX_DEFAULT, help=f"File name suffix to match (default: {SUFFIX_DEFAULT})")
    parser.add_argument("--dry-run", dest="dry_run", action=argparse.BooleanOptionalAction, default=DRY_RUN,
                        help="Preview deletions without performing them (default: True). Use --no-dry-run to actually delete.")
    args = parser.parse_args()

    # Ensure prefix has no leading slash, S3 keys shouldn't start with '/'
    prefix = args.prefix.lstrip("/")

    asyncio.run(run(args.bucket, prefix, args.suffix, args.dry_run))

if __name__ == "__main__":
    main()
