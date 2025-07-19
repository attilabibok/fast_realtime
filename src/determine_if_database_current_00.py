# FAST-realtime update
# Script 00 - determine_if_database_current_00
#
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
import s3fs
import psycopg2
from sqlalchemy import create_engine

import argparse
import configparser
import time
import datetime
import warnings
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


# -----------------
def fn_parse_iso8601_date_from_s3(str_s3_filepath):
    # Use regex to extract date and hour
    match = re.search(r'nwm\.(\d{8})/.*?\.t(\d{2})z', str_s3_filepath)
    if match:
        date_part = match.group(1)      # '20250503'
        hour_part = match.group(2)      # '17'
        iso8601_str = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}T{hour_part}:00:00"
        return(iso8601_str)
    else:
        return(None)
# -----------------


# ~~~~~~~~~~~~~~~~~~~~~~
def fn_determine_current_forecast():
    # get Short-range from AWS nwm
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    
    result = []

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
            #print(f"  -- Found valid forecast group in {date_prefix}:")
            break
        else:
            #print(f"  -- No valid forecast group found in {date_prefix}")
            pass

    return(result)
# ~~~~~~~~~~~~~~~~~~~~~~


# ------------
def fn_get_dataframe_from_postgresql(str_table_name, dict_db_params):
    conn = psycopg2.connect(
        host=dict_db_params.get("host"),
        user=dict_db_params.get("user"),
        password=dict_db_params.get("password"),
        dbname=dict_db_params.get("dbname")
    )

    cur = conn.cursor()
    query = f"SELECT * FROM public.{str_table_name}"
    cur.execute(query)
    rows = cur.fetchall()
    colnames = [desc[0] for desc in cur.description]
    df = pd.DataFrame(rows, columns=colnames)
    cur.close()
    conn.close()

    return df
# ------------


# .........................................................
def fn_determine_if_database_current(str_config_file_path, b_print_output):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    
    b_needs_update = False

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|              DETERMINE IF FAST DATABASE IS CURRENT              |")
        print("|                Created by Andy Carter, PE of                    |")
        print("|             Center for Water and the Environment                |")
        print("|                 University of Texas at Austin                   |")
        print("+-----------------------------------------------------------------+")
        print("  ---(c) INPUT GLOBAL CONFIGURATION FILE: " + str_config_file_path)
        print("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        print("===================================================================")
    else:
        print('Step 0: Determine if FAST database is current')
        
    # --- Read variables from config.ini ---
    config = configparser.ConfigParser()
    config.read(str_config_file_path)
    
    if 'database' in config:
        section = config['database']
        
        # Database connection configuration
        dict_db_params = {
            'host': section.get('host', ''),
            'dbname': section.get('dbname', ''),
            'user': section.get('username', ''),
            'password': section.get('password', '')
        }
        
        # Overwrite with environment variable if password is 'xxx'
        if dict_db_params['password'] == 'xxx':
            dict_db_params['password'] = os.environ.get('DB_PASSWORD', '')
    else:
        raise KeyError("Missing [database] section in config file")
    
    # -- From the s3 bucket,determine the current NWM forecast
    result = fn_determine_current_forecast()
    str_iso8601_time = fn_parse_iso8601_date_from_s3(result[0])
    if b_print_output:
        print(f'  --  Current NWM forecast:  {str_iso8601_time}')
    
    # -- From the FAST database, determine the last update time
    df_current_forecast = fn_get_dataframe_from_postgresql('t_current_forecast', dict_db_params)
    str_current_db_forecast = df_current_forecast.iloc[0]['model_run_time']
    if b_print_output:
        print(f'  -- Current FAST forecast: {str_current_db_forecast}')
    
    if str_iso8601_time != str_current_db_forecast:
        print('  -- Update of FAST database required')
        b_needs_update = True
    else:
        print('  -- FAST database is current')
        
    return(b_needs_update)
# .........................................................


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':

    flt_start_run = time.time()
    
    parser = argparse.ArgumentParser(description='========= DETERMINE IF FAST DATABASE IS CURRENT =========')
    
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

    b_needs_update = fn_determine_if_database_current(str_config_file_path, b_print_output)

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)
    
    print('Compute Time: ' + str(time_pass))
 #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~