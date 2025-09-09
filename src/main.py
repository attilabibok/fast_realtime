from fastapi import FastAPI
import boto3                 
from botocore import UNSIGNED     
from botocore.config import Config 
from fastapi.responses import PlainTextResponse
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import asyncio
import logging
import os
import time
from generate_treeview import generate_html
from fast_realtime_batch import process_all_ini_files_parallel  # <- your current module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

FOLDER_PATH_DA = Path("/fast_realtime/src/txdot_dist_local_da")
FOLDER_PATH_NWM = Path("/fast_realtime/src/txdot_dist_local_nwm")
FILE_DA_FINAL = "/fast_realtime/src/config_FULL_DA.ini"
FILE_DA_INPUT = "/fast_realtime/src/config_FULL_DA_input.ini"
FILE_NWM_FINAL = "/fast_realtime/src/config_FULL_NWM.ini"
FILE_NWM_INPUT = "/fast_realtime/src/config_FULL_NWM_input.ini"

# FILE_NWM2_INPUT = "/fast_realtime/src/config_FULL_NWM2_input.ini"
# FOLDER_PATH_NWM2 = Path("/fast_realtime/src/txdot_dist_local_nwm2")
# FILE_NWM2_FINAL = "/fast_realtime/src/config_FULL_NWM2.ini"

FOLDER_PATH_DA_NC = Path("/fast_realtime/src/txdot_dist_local_da_nowcast")
FOLDER_PATH_NWM_NC = Path("/fast_realtime/src/txdot_dist_local_nwm_nowcast")
FILE_NWM_INPUT_NC = "/fast_realtime/src/config_FULL_NWM_nc_input.ini"
FILE_DA_INPUT_NC = "/fast_realtime/src/config_FULL_DA_nc_input.ini"
FILE_DA_FINAL_NC = "/fast_realtime/src/config_FULL_DA_nc.ini"
FILE_NWM_FINAL_NC = "/fast_realtime/src/config_FULL_NWM_nc.ini"

PRINT_OUTPUT = False
MAX_WORKERS = int(os.getenv("MAX_PROCESSES", "3"))
SLEEP_TIME = int(os.getenv("SLEEP_TIME", "1800"))


def run_update():

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL_NC, initial_ini_str=FILE_NWM_INPUT_NC)
    duration = str(timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL, initial_ini_str=FILE_NWM_INPUT)
    duration = str(timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM .ini files processed in: {duration}")

    # start = time.time()
    # process_all_ini_files_parallel(FOLDER_PATH_NWM2, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM2_FINAL, initial_ini_str=FILE_NWM2_INPUT)
    # duration = str(timedelta(seconds=int(time.time() - start)))
    # logger.info(f"[✓] All NWM .ini files from original NWM processed in: {duration}")
    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_DA_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL_NC, initial_ini_str=FILE_DA_INPUT_NC)
    duration = str(timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All DA NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_DA, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL, initial_ini_str=FILE_DA_INPUT)
    duration = str(timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All DA .ini files processed in: {duration}")

    start = time.time()
    # S3 HTML index generation tasks
    BUCKET_NAME = "knatempstorage"
    OUTPUT_HTML = "tree.html"
    html_tasks = [
        # generate_html(bucket=BUCKET_NAME, prefix="fast_historic/da/", output_html=OUTPUT_HTML, s3_upload=True),
        # generate_html(bucket=BUCKET_NAME, prefix="fast_historic/nwm/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm/", output_html=OUTPUT_HTML, s3_upload=True),
        # generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm2/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm_nc/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da_nc/", output_html=OUTPUT_HTML, s3_upload=True),

        generate_html(bucket=BUCKET_NAME, prefix="nwm_txdot_output/short_range_da_kf/hist/", output_html=OUTPUT_HTML, s3_upload=True),
    ]

    # Run async index generation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(*html_tasks))
    loop.close()

    total_duration = timedelta(seconds=int(time.time() - start))
    logger.info(f"All {OUTPUT_HTML}'s uploaded to S3 bucket :{BUCKET_NAME} in {total_duration}")


WATCH_BUCKET = os.getenv("WATCH_BUCKET", "knatempstorage")
WATCH_KEY = os.getenv("WATCH_KEY","nwm_txdot_output/short_range_da_kf/streamflow_kf_sr.nc")  
WATCH_PREFIX = os.getenv("WATCH_PREFIX","nwm_txdot_output/short_range_da_kf/")  
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60"))

# One-time S3 client
_s3 = boto3.client(
    "s3",
    config=Config(signature_version=UNSIGNED)
)

def _get_latest_object_info(bucket: str, key: str | None = None, prefix: str | None = None):
    """
    Return (object_key, last_modified: datetime, etag: str) for:
      - exact key via HeadObject; or
      - newest object under prefix via ListObjectsV2 paginator.

    Raises if nothing is found (for prefix).
    """
    if key:
        head = _s3.head_object(Bucket=bucket, Key=key)
        return key, head["LastModified"], head["ETag"].strip('"')

    if not prefix:
        raise ValueError("Provide either WATCH_KEY or WATCH_PREFIX")

    paginator = _s3.get_paginator("list_objects_v2")
    newest = None
    new_key = None
    new_etag = None

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        contents = page.get("Contents")
        if not contents:
            continue
        for obj in contents:
            lm = obj["LastModified"]
            if newest is None or lm > newest:
                newest = lm
                new_key = obj["Key"]
                new_etag = obj.get("ETag", "").strip('"')

    if newest is None:
        raise FileNotFoundError(f"No objects found under prefix '{prefix}' in bucket '{bucket}'")

    return new_key, newest, new_etag

def _humanize_delta(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    units = [
        ("day", 86400),
        ("hour", 3600),
        ("minute", 60),
        ("second", 1),
    ]
    parts = []
    for name, secs in units:
        val, total = divmod(total, secs)
        if val:
            parts.append(f"{val} {name}{'s' if val != 1 else ''}")
    return ", ".join(parts) if parts else "0 seconds"

@asynccontextmanager
async def lifespan(app: FastAPI):
    async def scheduler():
        """
        On startup:
          - Find latest S3 object and force a full update once (idempotent).
        Afterwards:
          - Poll S3 every WATCH_INTERVAL_SECONDS, and run update only when a new object appears.
        Also logs the age of the last processed file.
        """
        last_seen_signature = None

        # Track the last object we actually executed the update on
        last_processed_key: str | None = None
        last_processed_modified: datetime | None = None
        last_processed_etag: str | None = None

        # ----- BOOTSTRAP: Run once at startup on the latest object -----
        try:
            key, last_modified, etag = await asyncio.to_thread(
                _get_latest_object_info, WATCH_BUCKET, WATCH_KEY, WATCH_PREFIX
            )
            last_seen_signature = f"{key}:{etag}:{int(last_modified.timestamp())}"

            logger.info(
                f"🚀 Startup: forcing update on latest object "
                f"s3://{WATCH_BUCKET}/{key} (ETag={etag}, LastModified={last_modified.isoformat()})"
            )

            # Run the full update once at startup
            await asyncio.to_thread(run_update)

            # Mark what we actually ran on
            last_processed_key = key
            last_processed_modified = last_modified
            last_processed_etag = etag

            if SLEEP_TIME > 0:
                logger.info(f"Startup cool-down for {SLEEP_TIME//60} minutes...")
                await asyncio.sleep(SLEEP_TIME)

        except FileNotFoundError as e:
            logger.warning(f"Startup S3 lookup: {e} — entering watch loop without initial run.")
        except Exception as e:
            logger.exception(f"Startup update failed: {e} — entering watch loop anyway.")

        # ----- CONTINUOUS WATCH LOOP -----
        while True:
            try:
                key, last_modified, etag = await asyncio.to_thread(
                    _get_latest_object_info, WATCH_BUCKET, WATCH_KEY, WATCH_PREFIX
                )
                sig = f"{key}:{etag}:{int(last_modified.timestamp())}"

                if last_seen_signature is None:
                    # First successful discover (e.g., startup failed earlier)
                    last_seen_signature = sig
                    logger.info(
                        f"🔎 S3 watch initialized. Latest object: s3://{WATCH_BUCKET}/{key} "
                        f"(ETag={etag}, LastModified={last_modified.isoformat()})"
                    )

                elif sig != last_seen_signature:
                    logger.info(
                        f"Detected new S3 object: s3://{WATCH_BUCKET}/{key} "
                        f"(ETag={etag}, LastModified={last_modified.isoformat()}). Running update…"
                    )
                    await asyncio.to_thread(run_update)
                    last_processed_key = key
                    last_processed_modified = last_modified
                    last_processed_etag = etag
                    last_seen_signature = sig

                    if SLEEP_TIME > 0:
                        logger.info(f"Cooling down for {SLEEP_TIME//60} minutes...")
                        await asyncio.sleep(SLEEP_TIME)

            except FileNotFoundError as e:
                logger.warning(f"S3 watch: {e}")
            except Exception as e:
                logger.exception(f"S3 watch error: {e}")

            # Report age of the last processed file (if any)
            if last_processed_modified is not None:
                now = datetime.now(timezone.utc)
                age = now - last_processed_modified
                logger.info(
                    "✅ Last executed on: s3://%s/%s (ETag=%s, LastModified=%s) | Age now: %s",
                    WATCH_BUCKET,
                    last_processed_key,
                    last_processed_etag,
                    last_processed_modified.isoformat(),
                    _humanize_delta(age),
                )
            else:
                logger.info("No processed object yet in this session.")

            logger.info("⏳ Waiting %s seconds until next check…", WATCH_INTERVAL_SECONDS)
            await asyncio.sleep(WATCH_INTERVAL_SECONDS)

    asyncio.create_task(scheduler())
    yield  # application startup happens here


app = FastAPI(lifespan=lifespan)

@app.get("/trigger-update")
async def trigger_batch_run():
    logger.info("Manual trigger received...")
    await asyncio.to_thread(run_update)
    return {"status": "Update started in background"}


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "OK"