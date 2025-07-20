import time
import datetime
import argparse
from pathlib import Path
from tqdm import tqdm
import concurrent.futures

# Assuming this is your actual update function
from fast_realtime_update import fn_fast_realtime_update, fn_str_to_bool

def run_single_update(ini_file: Path, print_output: bool) -> tuple[str, str, float, str]:
    """Wrap the update function to use in multiprocessing."""
    start = time.time()
    try:
        fn_fast_realtime_update(str(ini_file), print_output)
        duration = time.time() - start
        return (ini_file.name, "success", duration, "")
    except Exception as e:
        duration = time.time() - start
        return (ini_file.name, "failed", duration, str(e))


def process_all_ini_files_parallel(folder_path: Path, print_output: bool = True, max_workers: int = 4):
    ini_files = sorted(folder_path.glob("*.ini"))
    if not ini_files:
        print(f"[!] No .ini files found in {folder_path}")
        return

    print(f"[i] Processing 1st file in single-process mode...\n")
    first_ini = ini_files[0]
    name, status, dur, msg = run_single_update(first_ini, print_output)
    duration_str = str(datetime.timedelta(seconds=int(dur)))
    if status == "success":
        print(f"[✓] Done: {name} | Duration: {duration_str}")
    else:
        print(f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}")

    # Remaining files
    remaining_inis = ini_files[1:]
    if not remaining_inis:
        return

    print(f"\n[i] Processing remaining {len(remaining_inis)} files in parallel using {max_workers} workers...\n")

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(run_single_update, ini_file, print_output)
            for ini_file in remaining_inis
        ]

        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Processing"):
            name, status, dur, msg = future.result()
            duration_str = str(datetime.timedelta(seconds=int(dur)))
            if status == "success":
                print(f"[✓] Done: {name} | Duration: {duration_str}")
            else:
                print(f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}")

    print(f"[i] Processing statewide file in single-process mode...\n")
    name, status, dur, msg = run_single_update(Path("src/config_FULL_hand_linux_v2.ini"), print_output)
    duration_str = str(datetime.timedelta(seconds=int(dur)))
    if status == "success":
        print(f"[✓] Done: {name} | Duration: {duration_str}")
    else:
        print(f"[✗] Failed: {name} | Duration: {duration_str} | Error: {msg}")

def process_all_ini_files(folder_path: Path, print_output: bool = True):
    ini_files = list(folder_path.glob("*.ini"))

    if not ini_files:
        print(f"[!] No .ini files found in {folder_path}")
        return

    for ini_file in tqdm(ini_files, desc="Processing INI files"):
        print(f"\n[+] Running: {ini_file.name}")
        start = time.time()

        try:
            fn_fast_realtime_update(str(ini_file), print_output)
        except Exception as e:
            print(f"[!] Failed processing {ini_file.name}: {e}")

        duration = datetime.timedelta(seconds=int(time.time() - start))
        print(f"[✓] Done: {ini_file.name} | Duration: {duration}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run FAST realtime update for all .ini configs in a folder")

    parser.add_argument(
        "-f", "--folder",
        help="Path to folder containing .ini files",
        type=Path,
        required=True
    )

    parser.add_argument(
        "-r", "--print-output",
        help="Print output messages (default: True)",
        type=fn_str_to_bool,
        default=True
    )

    args = parser.parse_args()

    total_start = time.time()
    # process_all_ini_files(args.folder, args.print_output)
    process_all_ini_files_parallel(args.folder, args.print_output, max_workers=8)
    total_duration = datetime.timedelta(seconds=int(time.time() - total_start))
    print(f"\n[✓] All .ini files processed in: {total_duration}")
