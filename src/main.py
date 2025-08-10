from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import logging
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

FOLDER_PATH_DA = Path("./src/txdot_dist_local_da")
FOLDER_PATH_NWM = Path("./src/txdot_dist_local_nwm")
FILE_DA_FINAL = "/fast_realtime/src/config_FULL_hand_linux_DA.ini"
FILE_NWM_FINAL = "/fast_realtime/src/config_FULL_hand_linux_NWM.ini"


FOLDER_PATH_DA_NC = Path("./src/txdot_dist_local_da_nowcast")
FOLDER_PATH_NWM_NC = Path("./src/txdot_dist_local_nwm_nowcast")
FILE_DA_FINAL_NC = "/fast_realtime/src/config_FULL_hand_linux_DA_nc.ini"
FILE_NWM_FINAL_NC = "/fast_realtime/src/config_FULL_hand_linux_NWM_nc.ini"

PRINT_OUTPUT = False
MAX_WORKERS = 6


def run_update():

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL_NC)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_NWM, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_NWM_FINAL)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All NWM .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_DA_NC, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL_NC)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All DA NC .ini files processed in: {duration}")

    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH_DA, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All DA .ini files processed in: {duration}")

    start = time.time()
    # S3 HTML index generation tasks
    BUCKET_NAME = "knatempstorage"
    OUTPUT_HTML = "tree.html"
    html_tasks = [
        generate_html(bucket=BUCKET_NAME, prefix="fast_historic/da/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_historic/nwm/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm_nc/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da_nc/", output_html=OUTPUT_HTML, s3_upload=True),
    ]

    # Run async index generation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(*html_tasks))
    loop.close()

    total_duration = datetime.timedelta(seconds=int(time.time() - start))
    logger.info(f"All {OUTPUT_HTML}'s uploaded to S3 bucket :{BUCKET_NAME} in {total_duration}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def scheduler():
        while True:
            logger.info("⏳ Scheduled FAST update starting...")
            await asyncio.to_thread(run_update)
            logger.info("✅ Scheduled FAST update complete. Sleeping for 5 minutes...")
            await asyncio.sleep(60 * 60)

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