import asyncio
import time
import datetime
import argparse
import traceback
from pathlib import Path
from tqdm import tqdm
import concurrent.futures

# Assuming this is your actual update function
from fast_realtime_update import fn_str_to_bool
from utils import load_config, TqdmToLogger
from fast import run_fast_realtime_update
from generate_treeview import generate_html
import logging
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
tqdm_logger = TqdmToLogger(logger)


def run_single_update(
    ini_file: Path, print_output: bool
) -> tuple[str, str, float, str]:
    """Wrap the update function to use in multiprocessing."""
    start = time.time()
    try:
        cfg = load_config(ini_file)
        run_fast_realtime_update(cfg, print_output)
        duration = time.time() - start
        return (ini_file.name, "success", duration, "")
    except Exception as e:
        duration = time.time() - start
        tb = traceback.format_exc()
        return (ini_file.name, "failed", duration, tb)


def process_all_ini_files_parallel(
    folder_path: Path, print_output: bool = True, max_workers: int = 4, final_ini_str: Optional[str] = None, initial_ini_str: Optional[str] = None
):
    ini_files = sorted(folder_path.glob("*.ini"))
    if not ini_files:
        logger.error(f"[!] No .ini files found in {folder_path}")
        return

    if initial_ini_str:
        txfull_init = Path(initial_ini_str).resolve()
        name, status, dur, msg = run_single_update(txfull_init, print_output)

        duration_str = str(datetime.timedelta(seconds=int(dur)))
        if status == "success":
            logger.info(f"[✓] Init step Done: {name} | Duration: {duration_str}")
        else:
            logger.error(f"[✗] Init step Failed: {name} | Duration: {duration_str} | Error: {msg}")

        remaining_inis = ini_files

    else:
        logger.debug("[i] Processing 1st file in single-process mode...")
        first_ini = ini_files[0]
        name, status, dur, msg = run_single_update(first_ini, print_output)
        duration_str = str(datetime.timedelta(seconds=int(dur)))
        if status == "success":
            logger.info(f"[✓] Done: {name} | Duration: {duration_str}")
        else:
            logger.error(f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}")

        # Remaining files
        remaining_inis = ini_files[1:]
        if not remaining_inis:
            return

    logger.debug(
        f"[i] Processing remaining {len(remaining_inis)} files in parallel using {max_workers} workers..."
    )

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(run_single_update, ini_file, print_output)
            for ini_file in remaining_inis
        ]

        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Processing",
            file=tqdm_logger,
            ncols=25,
            dynamic_ncols=True,
            ascii=True
        ):
            name, status, dur, msg = future.result()
            duration_str = str(datetime.timedelta(seconds=int(dur)))
            if status == "success":
                logger.info(f"[✓] Done: {name} | Duration: {duration_str}")
            else:
                logger.error(
                    f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}"
                )

    logger.info("[i] Processing statewide file in single-process mode...")

    if final_ini_str:
        txfull_config = Path(final_ini_str).resolve()
        name, status, dur, msg = run_single_update(txfull_config, print_output)
        duration_str = str(datetime.timedelta(seconds=int(dur)))
        if status == "success":
            logger.info(f"[✓] Final step Done: {name} | Duration: {duration_str}")
        else:
            logger.error(f"[✗] Final step Failed: {name} | Duration: {duration_str} | Error: {msg}")
    else:

        logger.warning(f"To finalizer .ini was defined. This step is skipped.")


def process_all_ini_files(folder_path: Path, print_output: bool = True):
    ini_files = list(folder_path.glob("*.ini"))

    if not ini_files:
        logger.error(f"[!] No .ini files found in {folder_path}")
        return

    for ini_file in tqdm(ini_files, desc="Processing INI files"):
        logger.debug(f"[+] Running: {ini_file.name}")
        start = time.time()

        try:
            cfg = load_config(str(ini_file))
            run_fast_realtime_update(cfg, print_output)
        except Exception as e:
            logger.error(f"[!] Failed processing {ini_file.name}: {e}")

        duration = datetime.timedelta(seconds=int(time.time() - start))
        logger.info(f"[✓] Done: {ini_file.name} | Duration: {duration}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch run FAST realtime update for all .ini configs in a folder"
    )
    parser.add_argument(
        "-f", "--folder",
        help="Path to folder containing .ini files",
        type=Path,
        default="./src/txdot_dist_local",
    )
    parser.add_argument(
        "-r", "--print-output",
        help="Print output messages (default: True)",
        type=fn_str_to_bool,
        default=False,
    )

    args = parser.parse_args()
    total_start = time.time()

    # Run update jobs synchronously (parallelized with ProcessPoolExecutor internally)
    process_all_ini_files_parallel(args.folder, args.print_output, max_workers=6)

    # S3 HTML index generation tasks
    BUCKET_NAME = "knatempstorage"
    OUTPUT_HTML = "tree.html"
    html_tasks = [
        generate_html(bucket=BUCKET_NAME, prefix="fast_historic/da/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/da/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_historic/nwm/", output_html=OUTPUT_HTML, s3_upload=True),
        generate_html(bucket=BUCKET_NAME, prefix="fast_realtime/nwm/", output_html=OUTPUT_HTML, s3_upload=True),
    ]

    # Run async index generation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(*html_tasks))
    loop.close()

    total_duration = datetime.timedelta(seconds=int(time.time() - total_start))
    logger.info(f"[✓] All .ini files processed in: {total_duration}")

if __name__ == "__main__":
    main()