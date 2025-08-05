# FAST-realtime update
# Script 01A - populate_t_flow_forecast_from_NWM_01A
#
# From the NWM bucket 'noaa-nwm-pds', find the most current short range forecast
# of streamflow list s3://noaa-nwm-pds/nwm.20250503/short_range/nwm.t14z.short_range.channel_rt.f001.conus.nc
# s3://noaa-nwm-pds/nwm.20250503/short_range/nwm.t14z.short_range.channel_rt.f002.conus.nc .. to 018.
# Process these multiple netCDFs into a single table of flow (converted to cfs)
# Format this table to 't_flow_forecast'  for FAST database and push to the PostgreSQL
#
# Created by: Andy Carter, PE
# Created - 2025.05.03
# ************************************************************

# ************************************************************
import boto3
from botocore import UNSIGNED
from botocore.config import Config
import re
import pandas as pd
import xarray as xr
import s3fs
import concurrent.futures
from sqlalchemy import create_engine, text
import warnings
import time
import datetime
import argparse
from pathlib import Path
from utils import FASTConfig, load_config, resolve_db_credentials

import logging
logger = logging.getLogger(__name__)


def fn_feature_id_list_from_file(path: Path):
    with xr.open_dataset(path) as ds:
        return list(ds['feature_id'].values)


def fn_open_and_process_local_dataset(path: Path):
    dataset = xr.open_dataset(path)
    dataset = dataset.drop_vars(set(dataset.variables) - {'streamflow', 'reference_time'})
    dataset.load()
    return dataset


def fn_streamflow_from_list_valid_files(list_valid_files, str_bucket, cache_dir='forecast_cache'):
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    fs = s3fs.S3FileSystem(anon=True)

    logger.info("  -- Caching S3 NetCDF files if not already downloaded...")
    local_paths = []
    for s3_key in list_valid_files:
        filename = s3_key.replace('/', '_')
        local_file = cache_path / filename
        if not local_file.exists():
            with fs.open(f'{str_bucket}/{s3_key}', 'rb') as remote_file, open(local_file, 'wb') as out_file:
                out_file.write(remote_file.read())
        local_paths.append(local_file)

    logger.info("  -- Opening datasets in parallel...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        list_datasets = list(executor.map(fn_open_and_process_local_dataset, local_paths))

    feature_id_list = fn_feature_id_list_from_file(local_paths[0])

    logger.info("  -- Aggregating forecast data...")
    ds = xr.concat(list_datasets, dim='time')
    utc_forecast_time = ds['reference_time'].values
    numpy_array = ds['streamflow'].values
    ds.close()

    df = pd.DataFrame(numpy_array, columns=feature_id_list)
    df_flow_cfs = df * 35.3147
    return df_flow_cfs, utc_forecast_time


def fn_get_valid_forecast_group(date_prefix, bucket_name, file_pattern):
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    short_range_prefix = date_prefix + 'short_range/'
    forecast_groups = {}

    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket_name, Prefix=short_range_prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            match = file_pattern.search(key)
            if match:
                t_hour = match.group(1)
                group_key = f"t{t_hour}z"
                forecast_groups.setdefault(group_key, []).append(key)

    for group_key in sorted(forecast_groups.keys(), reverse=True):
        if len(forecast_groups[group_key]) >= 18:
            return forecast_groups[group_key]
    return None


def fn_format_flow_table(df, utc_time, feature_ids_path: Path):
    df_feature_ids = pd.read_csv(feature_ids_path)
    columns_to_keep = df_feature_ids.iloc[:, 0].tolist()
    df_filtered = df[columns_to_keep].fillna(0).astype(int).transpose()
    df_filtered.columns = [f'flow_t{str(i).zfill(2)}' for i in range(df_filtered.shape[1])]
    df_filtered = df_filtered.reset_index(names='feature_id')
    df_filtered['model_run_time'] = pd.to_datetime(utc_time[0]).isoformat()
    cols = df_filtered.columns.tolist()
    cols.insert(1, cols.pop(cols.index('model_run_time')))
    return df_filtered[cols]


def fn_populate_t_flow_forecast_from_NWM(cfg: FASTConfig, b_print_output: bool = False):
    warnings.filterwarnings("ignore", category=UserWarning)

    logger.info(" ")
    if b_print_output:
        logger.info("+=================================================================+")
        logger.info("|          POPULATE t_flow_forecast FOR TEXAS FROM NWM S3         |")
        logger.info("|                Created by Andy Carter, PE of                    |")
        logger.info("|             Center for Water and the Environment                |")
        logger.info("|                 University of Texas at Austin                   |")
        logger.info("+-----------------------------------------------------------------+")
        logger.info(f"  ---(c) Loaded config for DB: {cfg.database.dbname} @ {cfg.database.host}")
        logger.info("===================================================================")
    else:
        logger.info('Step 1: Fetch NWM Flow Forecast')

    if not cfg.flow_from_nwm:
        raise ValueError("Missing [flow_from_nwm] section in config")

    feature_ids_path = Path(cfg.flow_from_nwm.texas_feature_id_list)

    bucket_name = 'noaa-nwm-pds'
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
    date_prefixes = sorted([
        p['Prefix'] for p in response.get('CommonPrefixes', []) if re.match(r'nwm\.\d{8}/', p['Prefix'])
    ], reverse=True)
    file_pattern = re.compile(r'nwm\.t(\d{2})z\.short_range\.channel_rt\.f(\d{3})\.conus\.nc')

    for date_prefix in date_prefixes:
        result = fn_get_valid_forecast_group(date_prefix, bucket_name, file_pattern)
        if result:
            break
    else:
        raise RuntimeError("No valid forecast group found")

    df, utc_time = fn_streamflow_from_list_valid_files(result, bucket_name)
    df_flow_forecast = fn_format_flow_table(df, utc_time, feature_ids_path)
    df_flow_forecast['workflow_id'] = cfg.sql.workflow_id or "default"

    logger.info('  -- Updating PostgreSQL... (~25 sec)')
    try:
        creds = resolve_db_credentials(cfg.database)
        connection_string = f"postgresql://{creds['user']}:{creds['password']}@{creds['host']}:{creds['port']}/{creds['dbname']}"
        engine = create_engine(connection_string)
        # Clean up existing rows for this workflow
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM t_flow_forecast WHERE workflow_id = :workflow_id"),
                {"workflow_id": df_flow_forecast['workflow_id'].iloc[0]},
            )
        # Insert new data
        df_flow_forecast.to_sql('t_flow_forecast', engine, if_exists='append', index=False)
        # df_flow_forecast.to_sql('t_flow_forecast', engine, if_exists='replace', index=False)
        # FIXME: DELETE THIS when in production. Ensure indexes exist
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_feature_id ON t_flow_forecast(feature_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_feature_id ON t_flow_forecast(model_run_time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_t_flow_forecast_workflow_id ON t_flow_forecast(workflow_id)"))
        logger.info("  -- Data successfully pushed to PostgreSQL")
    except Exception as e:
        logger.info(f" *** Database write failed: {e}")
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_populate_t_flow_forecast_from_NWM(cfg, b_print_output=not args.quiet)
    end = time.time()
    logger.info(f"Compute Time: {datetime.timedelta(seconds=int(end - start))}")