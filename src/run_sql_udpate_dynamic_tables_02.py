# FAST-realtime update
# Script 02 - run_sql_udpate_dynamic_tables_02
#
#
# Created by: Andy Carter, PE
# Created - 2025.05.01
# Revised - 2025.06.12 -- Allow Graceful Timeout of SQL
# ************************************************************


# ************************************************************
import argparse
import time
import datetime
import warnings

from utils import FASTConfig, load_config, resolve_db_credentials, fn_run_sql_script
# ************************************************************

import logging

logger = logging.getLogger(__name__)


# .........................................................
def fn_run_sql_udpate_dynamic_tables(
    cfg: FASTConfig, b_print_output: bool = True
) -> str:
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    if b_print_output:
        logger.info(
            "+=================================================================+"
        )
        logger.info(
            "|              UPDATE FAST DYNAMIC POSTGRES TABLES                |"
        )
        logger.info(
            "|                Created by Andy Carter, PE of                    |"
        )
        logger.info(
            "|             Center for Water and the Environment                |"
        )
        logger.info(
            "|                 University of Texas at Austin                   |"
        )
        logger.info(
            "+-----------------------------------------------------------------+"
        )
        logger.info("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        logger.info(
            "==================================================================="
        )
    else:
        logger.info("Step 2: Update realtime flood tables")

    if not cfg.sql:
        logger.warning("  !! Missing [sql] section in config")
        return "error"

    sql_file_path = cfg.sql.sql_file_path
    if not sql_file_path:
        logger.warning("  !! SQL file path not provided in config")
        return "error"

    logger.debug(f"SQL file: {sql_file_path}")

    try:
        db_config = resolve_db_credentials(cfg.database)
        result = fn_run_sql_script(db_config, sql_file_path)
        return result  # 'success', 'timeout', or 'error'
    except Exception as e:
        logger.error(f"  !! SQL execution failed: {e}")
        return "error"


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_run_sql_udpate_dynamic_tables(cfg, b_print_output=not args.quiet)
    end = time.time()
    logger.info(f"Compute Time: {datetime.timedelta(seconds=int(end - start))}")

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
