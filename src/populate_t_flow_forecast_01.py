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
from sqlalchemy import create_engine
import warnings
import time
import datetime
import argparse

from utils import load_config, FASTConfig, resolve_db_credentials


def fn_populate_t_flow_forecast(cfg: FASTConfig, b_print_output: bool = False):
    warnings.filterwarnings("ignore", category=UserWarning)

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|        POPULATE t_flow_forecast FOR TEXAS FROM KISTERS S3       |")
        print("|                Created by Andy Carter, PE of                    |")
        print("|             Center for Water and the Environment                |")
        print("|                 University of Texas at Austin                   |")
        print("+-----------------------------------------------------------------+")
        print(f"  ---(c) Loaded config for DB: {cfg.database.dbname} @ {cfg.database.host}")
        print("===================================================================")
    else:
        print('Step 1: Fetch NWM Flow Forecast')

    if not cfg.download:
        raise ValueError("[download] section is required in config")

    url = cfg.download.url
    download_dir = cfg.download.download_dir
    local_path = os.path.join(download_dir, 'valid_comids_texas_streamflow.nc')

    print('  -- Downloading netCDF forecast')
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        with open(local_path, 'wb') as f, tqdm(
            desc="  -- Downloading",
            total=total_size,
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
            ncols=60
        ) as bar:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    except Exception as e:
        print(f"Download failed: {e}")
        raise

    print('  -- Opening netCDF')
    try:
        with xr.open_dataset(local_path) as ds:
            print('  -- Converting netCDF')

            flow = (ds['streamflow'] * 35.3147).round().astype(int)
            time_labels = [f'flow_t{str(i).zfill(2)}' for i in range(flow.sizes['time'])]

            df = flow.to_dataframe().reset_index()
            df_pivot = df.pivot(index='feature_id', columns='time', values='streamflow')
            df_pivot.columns = time_labels
            df_pivot['model_run_time'] = pd.to_datetime(ds['reference_time'].values[0])
            df_final = df_pivot.reset_index()
            df_final = df_final[['feature_id', 'model_run_time'] + time_labels]
    except Exception as e:
        print(f"Failed to process NetCDF: {e}")
        raise

    print('  -- Updating PostgreSQL')
    try:
        creds = resolve_db_credentials(cfg.database)
        connection_string = (
            f"postgresql://{creds['user']}:{creds['password']}@{creds['host']}:{creds['port']}/{creds['dbname']}"
        )
        engine = create_engine(connection_string)
        df_final.to_sql('t_flow_forecast', engine, if_exists='replace', index=False)
        print("  -- Data successfully pushed to PostgreSQL")
    except Exception as e:
        print(f" *** Database write failed: {e}")
        raise

    try:
        os.remove(local_path)
        print(f"  -- Cleaned up: {local_path}")
    except Exception as e:
        print(f"Could not remove file: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_populate_t_flow_forecast(cfg, b_print_output=not args.quiet)
    end = time.time()
    print(f"\nCompute Time: {datetime.timedelta(seconds=int(end - start))}")
