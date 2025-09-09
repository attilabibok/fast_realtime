
from pathlib import Path
import logging
import os
from tqdm import tqdm
from datetime import timedelta
import time
import traceback
from fast import run_fast_realtime_update
from utils import load_config
from fast_realtime_batch import process_all_ini_files_parallel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s"

)
logger = logging.getLogger(__name__)

PRINT_OUTPUT = False
MAX_WORKERS = int(os.getenv("MAX_PROCESSES", "5"))

FOLDER_PATH_DA_HIST = Path("/fast_realtime/src/txdot_dist_local_da_hist")
FILE_DA_FINAL_HIST = "/fast_realtime/src/config_FULL_DA_hist.ini"
FILE_DA_INIT_HIST = "/fast_realtime/src/config_FULL_DA_hist_input.ini"

def run_update():
    # collect input netcdfs
    input_ini_path = Path(FILE_DA_INIT_HIST)
    streamflow_input_list = [] # filename list

    cfg = load_config(input_ini_path)
    if not cfg.download:
        raise KeyError(f"No download section is defined in the input configuration at: {input_ini_path}")

    streamflow_input_folder = Path(cfg.download.download_dir)

    if streamflow_input_folder.is_file():
        raise ValueError("A valid folder must be specified at download.download_dir!")

    streamflow_input_list = [p.name for p in streamflow_input_folder.iterdir() if p.is_file()]
    # run the historic update, do the input directly, do the rest in parallel without init

    for idx, input in tqdm(enumerate(streamflow_input_list), total=len(streamflow_input_list)):

        start = time.time()
        try:
            cfg.download.download_filename = input
            run_fast_realtime_update(cfg, print_output= False, enforce_update=True)
            duration = str(timedelta(seconds=int(time.time() - start)))
            logger.info(f"{idx}/{len(streamflow_input_list)} input:{input} DA historic INPUT .ini files processed in: {duration}")
        except Exception as e:
            duration = str(timedelta(seconds=int(time.time() - start)))
            tb = traceback.format_exc()
            logger.error(f"{idx}/{len(streamflow_input_list)} input:{input} | Error during Input step after  {duration}: {e}, {tb}")
        
        start = time.time()
        try:
            process_all_ini_files_parallel(FOLDER_PATH_DA_HIST, PRINT_OUTPUT, max_workers=MAX_WORKERS, final_ini_str=FILE_DA_FINAL_HIST)
            duration = str(timedelta(seconds=int(time.time() - start)))
            logger.info(f"{idx}/{len(streamflow_input_list)} input:{input} All historic DA .ini files processed in: {duration}")
        except Exception as e:
            duration = str(timedelta(seconds=int(time.time() - start)))
            tb = traceback.format_exc()
            logger.error(f"{idx}/{len(streamflow_input_list)} input:{input} | Error during processing step.{e}, {tb}")
    

if __name__ == "__main__":
    run_update()