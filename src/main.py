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
import datetime
from generate_treeview import generate_html
from fast_realtime_batch import process_all_ini_files_parallel  # <- your current module

app = FastAPI()

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

FILE_NWM2_INPUT = "/fast_realtime/src/config_FULL_NWM2_input.ini"
FOLDER_PATH_NWM2 = Path("/fast_realtime/src/txdot_dist_local_nwm2")
FILE_NWM2_FINAL = "/fast_realtime/src/config_FULL_NWM2.ini"

FOLDER_PATH_DA_NC = Path("/fast_realtime/src/txdot_dist_local_da_nowcast")
FOLDER_PATH_NWM_NC = Path("/fast_realtime/src/txdot_dist_local_nwm_nowcast")
FILE_DA_FINAL_NC = "/fast_realtime/src/config_FULL_DA_nc.ini"
FILE_NWM_FINAL_NC = "/fast_realtime/src/config_FULL_NWM_nc.ini"

PRINT_OUTPUT = False
MAX_WORKERS = int(os.getenv("MAX_PROCESSES", "4"))
SLEEP_TIME = int(os.getenv("SLEEP_TIME", "1800"))


def run_update():

    # start = time.time()
    # process_all_ini_files_parallel(FOLDER_PATH_NWM_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL_NC)
    # duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    # logger.info(f"[✓] All NWM NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL, initial_ini_str=FILE_NWM_INPUT)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM2, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM2_FINAL, initial_ini_str=FILE_NWM2_INPUT)
    duration = str(timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM .ini files from original NWM processed in: {duration}")
    # start = time.time()
    # process_all_ini_files_parallel(FOLDER_PATH_DA_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL_NC)
    # duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    # logger.info(f"[✓] All DA NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_DA, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL, initial_ini_str=FILE_DA_INPUT)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
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
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm2/", output_html=OUTPUT_HTML, s3_upload=True),
        # generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm_nc/", output_html=OUTPUT_HTML, s3_upload=True),
        # generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da_nc/", output_html=OUTPUT_HTML, s3_upload=True),
    ]

    # Run async index generation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(*html_tasks))
    loop.close()

    total_duration = datetime.timedelta(seconds=int(time.time() - start))
    logger.info(f"All {OUTPUT_HTML}'s uploaded to S3 bucket :{BUCKET_NAME} in {total_duration}")

WATCH_BUCKET = os.getenv("WATCH_BUCKET", "knatempstorage")
WATCH_KEY = os.getenv("WATCH_KEY","nwm_txdot_output/short_range_da_kf/valid_comids_texas_streamflow.nc")  
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def scheduler():
        """
        NEW: Poll S3 every WATCH_INTERVAL_SECONDS.
        Only when a new object (by LastModified+ETag) appears, run the update.
        """
        last_seen_signature = None

        while True:
            try:
                # Do the S3 check in a thread (boto3 is blocking)
                result = await asyncio.to_thread(
                    _get_latest_object_info,
                    WATCH_BUCKET,
                    WATCH_KEY,
                    WATCH_PREFIX,
                )
                key, last_modified, etag = result
                sig = f"{key}:{etag}:{int(last_modified.timestamp())}"

                if last_seen_signature is None:
                    last_seen_signature = sig
                    logger.info(
                        f"🔎 S3 watch initialized. Latest object: s3://{WATCH_BUCKET}/{key} "
                        f"(ETag={etag}, LastModified={last_modified.isoformat()})"
                    )
                    logger.info("First check, enforce update for the first time.")
                    await asyncio.to_thread(run_update)
                elif sig != last_seen_signature:
                    logger.info(
                        f"🆕 Detected new S3 object: s3://{WATCH_BUCKET}/{key} "
                        f"(ETag={etag}, LastModified={last_modified.isoformat()}). Running update…"
                    )
                    await asyncio.to_thread(run_update)
                    last_seen_signature = sig
                    # Optional: cool-down after a run (keeps your old SLEEP_TIME behavior)
                    if SLEEP_TIME > 0:
                        logger.info(f"😴 Cooling down for {SLEEP_TIME//60} minutes...")
                        await asyncio.sleep(SLEEP_TIME)

            except FileNotFoundError as e:
                logger.warning(f"S3 watch: {e}")
            except Exception as e:
                logger.exception(f"S3 watch error: {e}")

            # Poll period (1 minute default)
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