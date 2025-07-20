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
import os
import re
import pandas as pd
import xarray as xr
import s3fs
import concurrent.futures
from sqlalchemy import create_engine

import argparse
import configparser
import time
import datetime
import warnings
from pathlib import Path
# ************************************************************


# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist" % arg)
    else:
        # File exists so return the directory
        return arg
        return open(arg, 'r')  # return an open file handle
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


# ----------------
def fn_str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in {'true', 't', '1'}:
        return True
    elif value.lower() in {'false', 'f', '0'}:
        return False
    else:
        raise argparse.ArgumentTypeError(f"Boolean value expected. Got '{value}'.")
# ----------------



def fn_feature_id_list_from_file(path: Path):
    with xr.open_dataset(path) as ds:
        return list(ds['feature_id'].values)


def fn_open_and_process_local_dataset(path: Path):
    dataset = xr.open_dataset(path)
    dataset = dataset.drop_vars(set(dataset.variables) - {'streamflow', 'reference_time'})
    dataset.load()  # Now safe to load
    return dataset


def fn_streamflow_from_list_valid_files(list_valid_files, str_bucket, cache_dir='forecast_cache'):
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    fs = s3fs.S3FileSystem(anon=True)

    print("  -- Caching S3 NetCDF files if not already downloaded...")

    local_paths = []
    for s3_key in list_valid_files:
        filename = s3_key.replace('/', '_')  # sanitize
        local_file = cache_path / filename

        if not local_file.exists():
            with fs.open(f'{str_bucket}/{s3_key}', 'rb') as remote_file, open(local_file, 'wb') as out_file:
                out_file.write(remote_file.read())
        local_paths.append(local_file)


    print("  -- Opening datasets in parallel...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        list_datasets = list(executor.map(fn_open_and_process_local_dataset, local_paths))

    feature_id_list = fn_feature_id_list_from_file(local_paths[0])

    print("  -- Aggregating forecast data...")
    ds = xr.concat(list_datasets, dim='time')
    utc_forecast_time = ds['reference_time'].values
    numpy_array = ds['streamflow'].values
    ds.close()

    df = pd.DataFrame(numpy_array, columns=feature_id_list)
    df_flow_cfs = df * 35.3147
    return df_flow_cfs, utc_forecast_time

# ---------------------
def fn_get_valid_forecast_group(date_prefix, bucket_name, file_pattern):
    
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    
    """Check all forecast hours on a given date, and return the most recent with 18+ files."""
    short_range_prefix = date_prefix + 'short_range/'

    forecast_groups = {}  # Maps tXXz -> list of matching files

    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket_name, Prefix=short_range_prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            match = file_pattern.search(key)
            if match:
                t_hour = match.group(1)
                group_key = f"t{t_hour}z"
                forecast_groups.setdefault(group_key, []).append(key)

    # Sort by forecast group time, descending (e.g., t23z > t22z > ...)
    for group_key in sorted(forecast_groups.keys(), reverse=True):
        if len(forecast_groups[group_key]) >= 18:
            return forecast_groups[group_key]  # Return the first valid group

    return None  # No valid group for this day
# ---------------------


# ~~~~~~~~~~~~~~~~~~~~
def fn_format_flow_table(df, utc_time, str_texas_fature_id_filepath):
    
    # df is the short range forecast for the entire CONUS-18 hours
    # filter it down to Texas and format for 'FAST' databse table 't_flow_forecast'
    
    df_feature_ids = pd.read_csv(str_texas_fature_id_filepath)
    
    # Get the column names from the CSV (assuming they are listed in one column)
    columns_to_keep = df_feature_ids.iloc[:, 0].tolist()
    
    # Filter the original DataFrame
    df_filtered = df[columns_to_keep]
    
    del df
    
    df_filtered = df_filtered.fillna(0).astype(int)
    
    # Transpose the DataFrame
    df_transposed = df_filtered.transpose()
    
    del df_filtered
    
    # Rename the columns (flow_t00, flow_t01, ...)
    df_transposed.columns = [f'flow_t{str(i).zfill(2)}' for i in range(df_transposed.shape[1])]
    
    df_transposed = df_transposed.reset_index(names='feature_id')
    
    iso_time_str_clean = pd.to_datetime(utc_time[0]).isoformat()
    df_transposed['model_run_time'] = iso_time_str_clean
    
    # Move 'model_run_time' to the second column
    cols = df_transposed.columns.tolist()
    cols.insert(1, cols.pop(cols.index('model_run_time')))
    df_transposed = df_transposed[cols]
    
    return(df_transposed)
# ~~~~~~~~~~~~~~~~~~~~


# .........................................................
def fn_populate_t_flow_forecast_from_NWM(str_config_file_path, b_print_output):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|          POPULATE t_flow_forecast FOR TEXAS FROM NWM S3         |")
        print("|                Created by Andy Carter, PE of                    |")
        print("|             Center for Water and the Environment                |")
        print("|                 University of Texas at Austin                   |")
        print("+-----------------------------------------------------------------+")
        print("  ---(c) INPUT GLOBAL CONFIGURATION FILE: " + str_config_file_path)
        print("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        print("===================================================================")
    else:
        print('Step 1: Fetch NWM Flow Forecast')

    # --- Read variables from config.ini ---
    config = configparser.ConfigParser()
    config.read(str_config_file_path)

    if 'database' in config:
        section = config['database']
        
        username = section.get('username', '')
        password = section.get('password', '')
        host     = section.get('host', '')
        port     = section.get('port', '')
        dbname   = section.get('dbname', '')
        
        # Use environment variable if password is set as 'xxx' or blank
        if password in ('', 'xxx'):
            password = os.environ.get('DB_PASSWORD', '')
    else:
        raise KeyError("Missing [database] section in config file")
        
    if 'flow_from_nwm' in config:
        section = config['flow_from_nwm']
        
        str_texas_fature_id_filepath = section.get('texas_faeture_id_list', '')
    else:
        raise KeyError("Missing [flow_from_nwm] section in config file")
        
    # -------- get Short-range from AWS nwm
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    
    # ********* HARD CODED BUCKET **********
    bucket_name = 'noaa-nwm-pds'
    # ********* HARD CODED BUCKET **********
    
    base_prefix = ''  # Root of the bucket
    
    # Get the list of date folders (e.g., 'nwm.20250502/')
    response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
    date_prefixes = sorted(
        [p['Prefix'] for p in response.get('CommonPrefixes', []) if re.match(r'nwm\.\d{8}/', p['Prefix'])],
        reverse=True
    )
    
    # Regex pattern to extract time and forecast hour
    file_pattern = re.compile(r'nwm\.t(\d{2})z\.short_range\.channel_rt\.f(\d{3})\.conus\.nc')
    
    # Walk through dates, find the most recent day with valid forecast group
    for date_prefix in date_prefixes:
        result = fn_get_valid_forecast_group(date_prefix, bucket_name, file_pattern)
        if result:
            print(f"  -- Found valid forecast group in {date_prefix}:")
            for key in result:
                #print(f"  - {key}")
                pass
            break
        else:
            print(f"  -- No valid forecast group found in {date_prefix}")
            
    # 'result' is the list of most current complete s3 files in bucket
    df, utc_time = fn_streamflow_from_list_valid_files(result, bucket_name, )
    
    df_flow_forecast = fn_format_flow_table(df, utc_time, str_texas_fature_id_filepath)
    
    print('  -- Updating PostgreSQL... (~25 sec)')
    try:
        connection_string = f'postgresql://{username}:{password}@{host}:{port}/{dbname}'
        engine = create_engine(connection_string)
        df_flow_forecast.to_sql('t_flow_forecast', engine, if_exists='replace', index=False)
        print("  -- Data successfully pushed to PostgreSQL")
    except Exception as e:
        print(f" *** Database write failed: {e}")
        raise
# .........................................................


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':

    flt_start_run = time.time()
    
    parser = argparse.ArgumentParser(description='========= POPULATE t_flow_forecast FOR TEXAS FROM NWM S3 =========')
    
    parser.add_argument('-c',
                        dest = "str_config_file_path",
                        help=r'REQUIRED: Global configuration filepath Example:C:\Users\civil\dev\fast_realtime\src\config_realtime.ini',
                        required=True,
                        metavar='FILE',
                        type=lambda x: is_valid_file(parser, x))
    
    parser.add_argument('-r',
                    dest = "b_print_output",
                    help=r'OPTIONAL: Print output messages Default: True',
                    required=False,
                    default=True,
                    metavar='T/F',
                    type=fn_str_to_bool)
    
    args = vars(parser.parse_args())
    
    str_config_file_path = args['str_config_file_path']
    b_print_output = args['b_print_output']

    fn_populate_t_flow_forecast_from_NWM(str_config_file_path, b_print_output)

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)
    
    print('Compute Time: ' + str(time_pass))
 #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~