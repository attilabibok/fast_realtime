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
import logging

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
    folder_path: Path, print_output: bool = True, max_workers: int = 4
):
    ini_files = sorted(folder_path.glob("*.ini"))
    if not ini_files:
        logger.error(f"[!] No .ini files found in {folder_path}")
        return

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
            ascii=True,
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

    txfull_config = Path("/fast_realtime/src/config_FULL_hand_linux_DA.ini").resolve()
    name, status, dur, msg = run_single_update(txfull_config, print_output)
    duration_str = str(datetime.timedelta(seconds=int(dur)))
    if status == "success":
        logger.info(f"[✓] Done: {name} | Duration: {duration_str}")
    else:
        logger.error(f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch run FAST realtime update for all .ini configs in a folder"
    )

    parser.add_argument(
        "-f",
        "--folder",
        help="Path to folder containing .ini files",
        type=Path,
        # required=True,
        default="./src/txdot_dist_local",
    )

    parser.add_argument(
        "-r",
        "--print-output",
        help="Print output messages (default: True)",
        type=fn_str_to_bool,
        default=False,
    )

    args = parser.parse_args()

    total_start = time.time()
    # process_all_ini_files(args.folder, args.print_output)
    process_all_ini_files_parallel(args.folder, args.print_output, max_workers=6)
    total_duration = datetime.timedelta(seconds=int(time.time() - total_start))
    logger.info(f"[✓] All .ini files processed in: {total_duration}")
