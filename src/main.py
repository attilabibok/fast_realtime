from fastapi import FastAPI
from pathlib import Path
import asyncio
import logging
import time
import datetime
from fast_realtime_batch import process_all_ini_files_parallel  # <- your current module

app = FastAPI()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

FOLDER_PATH = Path("./src/txdot_dist_local")
PRINT_OUTPUT = False
MAX_WORKERS = 6


@app.get("/trigger-update")
async def trigger_batch_run():
    logger.info("Manual trigger received...")
    await asyncio.to_thread(run_update)
    return {"status": "Update started in background"}


def run_update():
    start = time.time()
    process_all_ini_files_parallel(FOLDER_PATH, PRINT_OUTPUT, max_workers=MAX_WORKERS)
    duration = str(datetime.timedelta(seconds=int(time.time() - start)))
    logger.info(f"[✓] All .ini files processed in: {duration}")


@app.on_event("startup")
async def start_scheduler():
    async def scheduler():
        while True:
            logger.info("⏳ Scheduled FAST update starting...")
            await asyncio.to_thread(run_update)
            logger.info("✅ Scheduled FAST update complete. Sleeping for 10 minutes...")
            await asyncio.sleep(10 * 60)

    asyncio.create_task(scheduler())
