from utils import FASTConfig, resolve_db_credentials

from determine_if_database_current_00 import fn_determine_if_database_current
from populate_t_flow_forecast_01 import fn_populate_t_flow_forecast
from populate_t_flow_forecast_from_NWM_01 import fn_populate_t_flow_forecast_from_NWM
from run_sql_udpate_dynamic_tables_02 import fn_run_sql_udpate_dynamic_tables
from create_s_bridge_warning_pnt_03 import fn_create_s_bridge_warning_pnt
from push_to_s3_04 import fn_push_to_s3
from push_full_to_s3 import fn_merged_view
import asyncio
import time
import datetime
import warnings

import logging
logger = logging.getLogger(__name__)


def log_duration(start: float, label: str):
    elapsed = time.time() - start
    logger.debug(f" {label} took: {datetime.timedelta(seconds=int(elapsed))}")

def run_fast_realtime_update(cfg: FASTConfig, print_output: bool = False, use_nwm: bool = True):
    warnings.filterwarnings("ignore", category=UserWarning)
    logger.info("+==================== FAST REALTIME ====================+")
    logger.info(f"  -- DB: {cfg.database.dbname} @ {cfg.database.host}:{cfg.database.port}")
    logger.info("+------------------------------------------------------+")

    step_start = time.time()
    needs_update = False
    enforce_update = False
    if cfg.sql or cfg.download or cfg.flow_from_nwm:
        needs_update = fn_determine_if_database_current(cfg, print_output)
    # TEMP override for testing
    # needs_update = True # FIXME: delete when deployed
    log_duration(step_start, "Step 1: Check for update")

    if (cfg.flow_from_nwm and cfg.flow_from_nwm.force) or (cfg.download and cfg.download.force):
        enforce_update = True
        logger.info("Update is enforced by the 'force' variable in the config")

    if needs_update or enforce_update:
        if use_nwm and cfg.flow_from_nwm:
            step_start = time.time()
            fn_populate_t_flow_forecast_from_NWM(cfg, print_output)
            log_duration(step_start, "Step 2: Populate from NWM")
        elif cfg.download:
            step_start = time.time()
            fn_populate_t_flow_forecast(cfg, print_output)
            log_duration(step_start, "Step 2: Populate from KISTERS")
        else:
            logger.warning("No valid forecast source configured. Local update is skipped. Ignore this warning if a foreign forecast table is used.")

        if cfg.sql:
            step_start = time.time()
            result = fn_run_sql_udpate_dynamic_tables(cfg, print_output)
            log_duration(step_start, "Step 3: Run SQL update")

            if result == 'success':
                step_start = time.time()
                if cfg.bridge_warnings.enabled:
                    fn_create_s_bridge_warning_pnt(cfg, print_output)
                    log_duration(step_start, "Step 4: Bridge warning")
                else:
                    log_duration(step_start, "Step 4: Bridge warning - SKIPPED !!!")

                if cfg.write_to_s3 or cfg.local_results:
                    step_start = time.time()
                    asyncio.run(fn_push_to_s3(cfg, print_output))
                    log_duration(step_start, "Step 5: Publishing")
                else:
                    step_start = time.time()
                    log_duration(step_start, "Step 5: Publishing- SKIPPED !!!")

            elif result == 'timeout':
                raise TimeoutError("SQL execution timed out")
            else:
                raise RuntimeError("SQL step failed")
        else:
            step_start = time.time()
            log_duration(step_start, "Step 3,4,5: SKIPPED !!!")
    else:
        logger.info("No update required. Skipping step 2,3,4,5.")

    if cfg.merged_view:
        step_start = time.time()
        asyncio.run(fn_merged_view(cfg, print_output))
        log_duration(step_start, "Step 6: Merged view")

