# FAST-realtime update
# Script 01B - populate_t_flow_forecast_01B
#
#
# Downloads a streamflow forecast (in NetCDF format) from a specified URL, 
# processes the data, and populates a PostgreSQL database table (t_flow_forecast)
# with the forecasted streamflow values for Texas. It reads configuration 
# settings from a file, handles data conversion, and handles the 
# download, processing, and cleanup of the downloaded file.
#
# Created by: Andy Carter, PE
# Created - 2025.05.01
# ************************************************************

# ************************************************************
import os
import xarray as xr
import pandas as pd
import requests
from tqdm import tqdm
from sqlalchemy import create_engine, text
import warnings
import time
import datetime
import argparse

import logging
from utils import load_config, FASTConfig, resolve_db_credentials, TqdmToLogger

logger = logging.getLogger(__name__)
tqdm_logger = TqdmToLogger(logger)

def fn_populate_t_flow_forecast(cfg: FASTConfig, b_print_output: bool = False):
    warnings.filterwarnings("ignore", category=UserWarning)

    if b_print_output:
        logger.info("+=================================================================+")
        logger.info("|        POPULATE t_flow_forecast FOR TEXAS FROM KISTERS S3       |")
        logger.info("|                Created by Andy Carter, PE of                    |")
        logger.info("|             Center for Water and the Environment                |")
        logger.info("|                 University of Texas at Austin                   |")
        logger.info("+-----------------------------------------------------------------+")
        logger.info(f"  ---(c) Loaded config for DB: {cfg.database.dbname} @ {cfg.database.host}")
        logger.info("===================================================================")
    else:
        logger.info('Step 1: Fetch NWM Flow Forecast')

    if not cfg.download:
        raise ValueError("[download] section is required in config")

    url = cfg.download.url
    download_dir = cfg.download.download_dir
    local_path = os.path.join(download_dir, 'valid_comids_texas_streamflow.nc')

    logger.debug('Checking if forecast file needs to be downloaded')
    should_download = cfg.download.force or not os.path.exists(local_path)
    logger.debug('Downloading netCDF forecast')
    if should_download:
        logger.info('Downloading netCDF forecast')
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            with open(local_path, 'wb') as f, tqdm(
                desc="Downloading",
                total=total_size,
                unit='B',
                file=tqdm_logger,
                unit_scale=True,
                unit_divisor=1024,
                ncols=60
            ) as bar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise
    else:
        logger.debug(f'File already exists at {local_path}, skipping download')

    logger.info('Opening netCDF')
    try:
        with xr.open_dataset(local_path) as ds:
            logger.debug('Converting netCDF')

            flow = (ds['streamflow'] * 35.3147).round().astype(int)
            time_labels = [f'flow_t{str(i).zfill(2)}' for i in range(flow.sizes['time'])]

            df = flow.to_dataframe().reset_index()
            df_pivot = df.pivot(index='feature_id', columns='time', values='streamflow')
            df_pivot.columns = time_labels
            df_pivot['model_run_time'] = pd.to_datetime(ds['reference_time'].values[0])
            df_final = df_pivot.reset_index()
            df_final = df_final[['feature_id', 'model_run_time'] + time_labels]

            # Add workflow_id
            df_final['workflow_id'] = cfg.sql.workflow_id or "default"

    except Exception as e:
        logger.error(f"Failed to process NetCDF: {e}")
        raise

    logger.info('Updating PostgreSQL')
    try:
        creds = resolve_db_credentials(cfg.database)
        connection_string = (
            f"postgresql://{creds['user']}:{creds['password']}@{creds['host']}:{creds['port']}/{creds['dbname']}"
        )
        engine = create_engine(connection_string)
        # Clean up existing rows for this workflow
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM t_flow_forecast WHERE workflow_id = :workflow_id"),
                {"workflow_id": df_final['workflow_id'].iloc[0]},
            )

        # Insert new data
        df_final.to_sql('t_flow_forecast', engine, if_exists='append', index=False)
        logger.info("Data successfully pushed to PostgreSQL")

        # FIXME: DELETE THIS when in production. Ensure indexes exist
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_feature_id ON t_flow_forecast(feature_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_feature_id ON t_flow_forecast(model_run_time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_workflow_id ON t_flow_forecast(workflow_id)"))
    except Exception as e:
        logger.error(f" *** Database write failed: {e}")
        raise e

    try:
        if cfg.download.cleanup_after_load:
            os.remove(local_path)
            logger.info(f"Cleaned up: {local_path}")
    except Exception as e:
        logger.error(f"Could not remove file: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_populate_t_flow_forecast(cfg, b_print_output=not args.quiet)
    end = time.time()
    logger.info(f"Compute Time: {datetime.timedelta(seconds=int(end - start))}")
