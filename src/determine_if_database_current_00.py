import warnings
import re
import boto3
import pandas as pd
from botocore import UNSIGNED
from botocore.config import Config
import psycopg2
from utils import FASTConfig, load_config, resolve_db_credentials, fn_get_dataframe_from_postgresql


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


def fn_parse_iso8601_date_from_s3(str_s3_filepath):
    match = re.search(r'nwm\.(\d{8})/.*?\.t(\d{2})z', str_s3_filepath)
    if match:
        date_part, hour_part = match.group(1), match.group(2)
        return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}T{hour_part}:00:00"
    return None


def fn_determine_current_forecast():
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    bucket_name = 'noaa-nwm-pds'

    response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
    date_prefixes = sorted([
        p['Prefix'] for p in response.get('CommonPrefixes', [])
        if re.match(r'nwm\.\d{8}/', p['Prefix'])
    ], reverse=True)

    file_pattern = re.compile(r'nwm\.t(\d{2})z\.short_range\.channel_rt\.f(\d{3})\.conus\.nc')

    for date_prefix in date_prefixes:
        result = fn_get_valid_forecast_group(date_prefix, bucket_name, file_pattern)
        if result:
            return result
    return None


def fn_determine_if_database_current(cfg: FASTConfig, print_output: bool = False) -> bool:
    warnings.filterwarnings("ignore", category=UserWarning)
    print("\nStep 0: Determine if FAST database is current") if not print_output else print("""
+=================================================================+
|              DETERMINE IF FAST DATABASE IS CURRENT              |
|                Created by Andy Carter, PE of                    |
|             Center for Water and the Environment                |
|                 University of Texas at Austin                   |
+-----------------------------------------------------------------+
  ---(c) Loaded config for DB: {} @ {}
  ---[r] PRINT OUTPUT: {}
===================================================================""".format(cfg.database.dbname, cfg.database.host, print_output))

    result = fn_determine_current_forecast()
    str_iso8601_time = fn_parse_iso8601_date_from_s3(result[0]) if result else None
    if print_output:
        print(f'  --  Current NWM forecast:  {str_iso8601_time}')

    db_conn_info = resolve_db_credentials(cfg.database)
    df_current = fn_get_dataframe_from_postgresql('t_current_forecast', db_conn_info)
    db_model_time = df_current.iloc[0]['model_run_time']
    if print_output:
        print(f'  -- Current FAST forecast: {db_model_time}')

    if str_iso8601_time != db_model_time:
        print('  -- Update of FAST database required')
        return True
    else:
        print('  -- FAST database is current')
        return False


if __name__ == '__main__':
    import argparse
    import time
    import datetime

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_determine_if_database_current(cfg, print_output=not args.quiet)
    end = time.time()
    print(f"\nCompute Time: {datetime.timedelta(seconds=int(end - start))}")
