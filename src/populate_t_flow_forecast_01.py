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


# .........................................................
def fn_populate_t_flow_forecast(str_config_file_path: str, b_print_output: bool = False):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|        POPULATE t_flow_forecast FOR TEXAS FROM KISTERS S3       |")
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

    if 'download' in config:
        section = config['download']
        
        url = section.get('url', '')
        download_dir = section.get('download_dir', '')
    else:
        raise KeyError("Missing [download] section in config file")

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
            ncols = 60
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
    
            cols = ['feature_id', 'model_run_time'] + time_labels
            df_final = df_final[cols]
    except Exception as e:
        print(f"Failed to process NetCDF: {e}")
        raise
        
    print('  -- Updating PostgreSQL')
    try:
        connection_string = f'postgresql://{username}:{password}@{host}:{port}/{dbname}'
        engine = create_engine(connection_string)
        df_final.to_sql('t_flow_forecast', engine, if_exists='replace', index=False)
        print("  -- Data successfully pushed to PostgreSQL")
    except Exception as e:
        print(f" *** Database write failed: {e}")
        raise
        
    # Cleanup
    try:
        os.remove(local_path)
        print(f"  -- Cleaned up: {local_path}")
    except Exception as e:
        print(f"Could not remove file: {e}")
# .........................................................



#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':

    flt_start_run = time.time()
    
    parser = argparse.ArgumentParser(description='========= POPULATE t_flow_forecast FOR TEXAS FROM KISTERS S3 =========')
    
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

    fn_populate_t_flow_forecast(str_config_file_path, b_print_output)

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)
    
    print('Compute Time: ' + str(time_pass))
 #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~