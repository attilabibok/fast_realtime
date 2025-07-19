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
import warnings
import os
import sys


# Import modules
from determine_if_database_current_00 import fn_determine_if_database_current
from populate_t_flow_forecast_01 import fn_populate_t_flow_forecast
from populate_t_flow_forecast_from_NWM_01 import fn_populate_t_flow_forecast_from_NWM
from run_sql_udpate_dynamic_tables_02 import fn_run_sql_udpate_dynamic_tables
from create_s_bridge_warning_pnt_03 import fn_create_s_bridge_warning_pnt
from push_to_s3_04 import fn_push_to_s3

# ************************************************************


# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist" % arg)
    else:
        # File exists so return the directory
        return arg
        return open(arg, "r")  # return an open file handle


# ----------------
def fn_str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in {"true", "t", "1"}:
        return True
    elif value.lower() in {"false", "f", "0"}:
        return False
    else:
        raise argparse.ArgumentTypeError(f"Boolean value expected. Got '{value}'.")

def log_duration(start_time, label):
    elapsed = time.time() - start_time
    print(f"  -- {label} took: {datetime.timedelta(seconds=int(elapsed))}")

# +++++++++++++++++++++++++++++
def fn_fast_realtime_update(
    str_config_file_path: str,
    b_print_output: bool = False,
    b_use_nwm: bool = True,
):

    step_start = time.time()
    # b_use_nwm = False # use the NWM s3 bucket, if False use KISTERs data assimilation

    # To supress the printing of Step output text
    # b_print_output = True

    # supress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    print(" ")
    print("+=================================================================+")
    print("|                  TxDOT FAST REALTIME UPDATE                     |")
    print("|                Created by Andy Carter, PE of                    |")
    print("|             Center for Water and the Environment                |")
    print("|                 University of Texas at Austin                   |")
    print("+-----------------------------------------------------------------+")
    print("  ---(c) INPUT GLOBAL CONFIGURATION FILE: " + str_config_file_path)
    print("+-----------------------------------------------------------------+")

    try:
        b_needs_update = fn_determine_if_database_current(
            str_config_file_path, b_print_output
        )
        # ************ Temp for testing
        b_needs_update = True
        # ************ Temp for testing
        log_duration(step_start, "Step 1: Determine if update is needed")

        if b_needs_update:
            if b_use_nwm:
                step_start = time.time()
                fn_populate_t_flow_forecast_from_NWM(
                    str_config_file_path, b_print_output
                )
                log_duration(step_start, "Step 2: Populate forecast from NWM")
            else:
                step_start = time.time()
                fn_populate_t_flow_forecast(str_config_file_path, b_print_output)
                log_duration(step_start, "Step 2: Populate forecast from local")

            step_start = time.time()
            str_status = fn_run_sql_udpate_dynamic_tables(
                str_config_file_path, b_print_output
            )
            log_duration(step_start, "Step 3: Update dynamic SQL tables")

            if str_status == "success":
                step_start = time.time()
                fn_create_s_bridge_warning_pnt(str_config_file_path, b_print_output)
                log_duration(step_start, "Step 4: Create bridge warnings")

                step_start = time.time()
                fn_push_to_s3(str_config_file_path, b_print_output)
                log_duration(step_start, "Step 5: Push output to S3")
            elif str_status == "timeout":
                print(" -- SQL timed out.")
                sys.exit(1)
            else:
                print(" -- SQL failed or config was invalid.")
                sys.exit(1)

        print("+-----------------------------------------------------------------+")

    except Exception as e:
        print("ERROR: Fast realtime update failed.")
        print(f"Reason: {str(e)}")
        raise  # re-raise if you want the traceback to bubble up


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":
    flt_start_run = time.time()
    try:
        parser = argparse.ArgumentParser(
            description="========= TxDOT FAST REALTIME UPDATE ========="
        )

        parser.add_argument(
            "-c",
            dest="str_config_file_path",
            help=r"REQUIRED: Global configuration filepath Example:C:\Users\civil\dev\fast_realtime\src\config_realtime.ini",
            required=True,
            metavar="FILE",
            type=lambda x: is_valid_file(parser, x),
        )

        parser.add_argument(
            "-r",
            dest="b_print_output",
            help=r"OPTIONAL: Print output messages Default: True",
            required=False,
            default=True,
            metavar="T/F",
            type=fn_str_to_bool,
        )

        args = vars(parser.parse_args())

        str_config_file_path = args["str_config_file_path"]
        b_print_output = args["b_print_output"]

        fn_fast_realtime_update(str_config_file_path, b_print_output)

        flt_end_run = time.time()
        flt_time_pass = (flt_end_run - flt_start_run) // 1
        time_pass = datetime.timedelta(seconds=flt_time_pass)
        print("Compute Time: " + str(time_pass))

    except Exception as e:
        print("\n[!] Script execution failed.")
        print(f"[!] {e}")
        exit(1)  # non-zero exit code indicates error

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
