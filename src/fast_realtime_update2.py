# This is the main orchestration script for "fast-realtime".  This requires
# a netCDF file where the 'short-range' forecasted flows are published.
# It then uses a series of static layers on a PostgreSQL / PostGIS database
# to create realtime road and bridge flooding layers
#
# Created by: Andy Carter, PE
# 2025.05.02

# ************************************************************
import argparse
import time
import datetime


# Import modules
from utils import load_config
from fast import run_fast_realtime_update

# ************************************************************


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="========= TxDOT FAST REALTIME UPDATE ========="
        )

        parser.add_argument(
            "-c",
            "--config",
            dest="config",
            required=True,
            help="Path to JSON or YAML config file",
        )
        parser.add_argument(
            "--nwm",
            action="store_true",
            dest="nwm",
            help="Use NWM forecast instead of KISTERS",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            dest="quiet",
            help="Suppress step output messages",
        )

        args = vars(parser.parse_args())
        cfg = load_config(args.get("config"))

        flt_start_run = time.time()

        run_fast_realtime_update(cfg, print_output=not args.get("quiet"), use_nwm=args.get("nwm"))

        flt_end_run = time.time()
        flt_time_pass = (flt_end_run - flt_start_run) // 1
        time_pass = datetime.timedelta(seconds=flt_time_pass)
        print("Compute Time: " + str(time_pass))

    except Exception as e:
        print("\n[!] Script execution failed.")
        print(f"[!] {e}")
        exit(1)  # non-zero exit code indicates error

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
