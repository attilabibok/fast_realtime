# FAST-realtime update
# Script 04 - push_to_s3_04
#
#
# Created by: Andy Carter, PE
# Created - 2025.05.03
# Revised - 2025.06.06 -- Subfolder allowed on S3 -- publish_sub_folder
# Revised - 2025.06.13 -- Revised to Esri.json  - commented out
# ************************************************************

# ************************************************************
import geopandas as gpd
import boto3
from io import BytesIO
import psycopg2
import argparse
import configparser
from shapely.geometry import MultiLineString, Point, Polygon
import os

import time
import datetime
import warnings

from pathlib import Path
import subprocess
import tempfile
import json
import warnings
#import esrijson
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


# ------------------
def fn_get_geodataframe_from_postgresql(table_name: str,
                                        db_params: dict,
                                        geom_col: str = 'geometry') -> gpd.GeoDataFrame:
    """
    Fetch a GeoDataFrame from a PostGIS table using psycopg2.

    Parameters:
        table_name (str): Name of the table in 'schema.table' or 'table' format.
        db_params (dict): Dictionary with keys: host, dbname, user, password, port.
        geom_col (str): Name of the geometry column.

    Returns:
        GeoDataFrame: The queried spatial data.
    """
    connection = psycopg2.connect(
        host=db_params.get("host"),
        dbname=db_params.get("dbname"),
        user=db_params.get("user"),
        password=db_params.get("password"),
        port=db_params.get("port", "5432")
    )

    try:
        sql = f"SELECT * FROM {table_name}"
        gdf = gpd.read_postgis(sql, con=connection, geom_col=geom_col)
    finally:
        connection.close()

    return gdf
# ------------------

# ----------------------
def fn_write_gdf_to_file(gdf, filepath):
    """
    Save a GeoDataFrame to a local GeoJSON file.

    Parameters:
        gdf (GeoDataFrame): The GeoDataFrame to save.
        filepath (str or Path): The full path to the output .geojson file.
    """

    # Ensure filepath is a Path object
    filepath = Path(filepath)

    # Create parent directories if they don't exist
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Convert datetime columns to ISO string format
    gdf = gdf.apply(lambda x: x.dt.strftime('%Y-%m-%dT%H:%M:%S') if x.dtype == 'datetime64[ns]' else x)

    # Write to file as GeoJSON
    gdf.to_file(filepath, driver='GeoJSON')
    print(f"  -- Saved to {filepath}")
# ----------------------

# ----------------------
def fn_write_gdf_to_s3(gdf, str_bucket_name, str_s3_key):

    # Convert datetime columns to string format
    gdf = gdf.apply(lambda x: x.dt.strftime('%Y-%m-%dT%H:%M:%S') if x.dtype == 'datetime64[ns]' else x)

    # Convert to GeoJSON in memory ---
    geojson_buffer = BytesIO()
    geojson_str = gdf.to_json()
    geojson_buffer.write(geojson_str.encode('utf-8'))
    geojson_buffer.seek(0)

    # Upload to S3 ---
    s3 = boto3.client('s3')
    s3.upload_fileobj(geojson_buffer, str_bucket_name, str_s3_key)
    print(f"  -- Uploaded to s3://{str_bucket_name}/{str_s3_key}")
# ----------------------


# ----------------------
def fn_write_gdf_to_s3_esrijson(gdf, str_bucket_name, str_s3_key):
    # Convert datetime columns to string ISO format
    gdf = gdf.apply(lambda x: x.dt.strftime('%Y-%m-%dT%H:%M:%S') if x.dtype == 'datetime64[ns]' else x)

    # Convert GeoDataFrame to GeoJSON string first
    geojson_str = gdf.to_json()

    # Convert GeoJSON string to Python dict
    geojson_dict = json.loads(geojson_str)

    # Convert GeoJSON dict to ESRI JSON string using esrijson.dumps()
    esri_json_str = esrijson.dumps(geojson_dict)

    # Upload ESRI JSON string to S3
    geojson_buffer = BytesIO(esri_json_str.encode('utf-8'))
    s3 = boto3.client('s3')
    s3.upload_fileobj(geojson_buffer, str_bucket_name, str_s3_key)

    print(f"  -- Uploaded ESRI JSON to s3://{str_bucket_name}/{str_s3_key}")
# ----------------------


# ----------------
def fn_assign_warn_class(row):
    if row['is_overtop'] == 1:
        return 'overtopped'
    elif row['min_dist_to_low_ch'] < 0.5:
        return 'critical'
    elif 0.5 <= row['min_dist_to_low_ch'] < 2:
        return 'high'
    elif 2 <= row['min_dist_to_low_ch'] < 5:
        return 'moderate'
    else:
        return 'low'
# ----------------


# .........................................................
def fn_push_to_s3(str_config_file_path, b_print_output):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|                   PUSH FAST LAYERS TO S3                        |")
        print("|                Created by Andy Carter, PE of                    |")
        print("|             Center for Water and the Environment                |")
        print("|                 University of Texas at Austin                   |")
        print("+-----------------------------------------------------------------+")
        print("  ---(c) INPUT GLOBAL CONFIGURATION FILE: " + str_config_file_path)
        print("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        print("===================================================================")
    else:
        print('Step 4: Uploading FAST Layers to S3')

    # --- Read variables from config.ini ---
    config = configparser.ConfigParser()
    config.read(str_config_file_path)
    
    if 'database' in config:
        section = config['database']
        
        # Database connection configuration
        db_params = {
            'host': section.get('host', ''),
            'dbname': section.get('dbname', ''),
            'user': section.get('username', ''),
            'password': section.get('password', ''),
            'port': section.get('port', '5432')
        }
        
        # Overwrite with environment variable if password is 'xxx'
        if db_params['password'] == 'xxx':
            db_params['password'] = os.environ.get('DB_PASSWORD', '')
    else:
        raise KeyError("Missing [database] section in config file")
        
    if 'write_to_s3' in config:
        section = config['write_to_s3']
        
        str_bucket_name = section.get('publish_bucket', '')
        
        # Handle optional publish_sub_folder
        str_publish_sub_folder = section.get('publish_sub_folder', '').strip()
        if str_publish_sub_folder and not str_publish_sub_folder.endswith('/'):
            str_publish_sub_folder += '/'
    else:
        warnings.warn("Missing [write_to_s3] section in config file", stacklevel=2)
        
    # table names in PostgreSQL
    str_bridge_table_name = 's_bridge_warning_pnt'
    str_road_nav_table_name = 's_flood_road_ln'
    str_road_table_name = 's_flood_road_trim_ln'
    str_inundation_table_name = 's_flood_merge_ar'
    
    gdf_s_bridge_warning_pnt = fn_get_geodataframe_from_postgresql(str_bridge_table_name, db_params,'geometry')
    gdf_s_flood_road_nav_ln = fn_get_geodataframe_from_postgresql(str_road_nav_table_name , db_params,'geometry')
    gdf_s_flood_road_trim_ln = fn_get_geodataframe_from_postgresql(str_road_table_name, db_params,'geometry')
    gdf_s_flood_merge_ar = fn_get_geodataframe_from_postgresql(str_inundation_table_name, db_params,'geometry')
    
    # Even if there are no polygons, this shold have one row with model_run_time
    str_model_run_time = gdf_s_flood_merge_ar.iloc[0]['model_run_time']
    
    geometry_fake_area = Polygon([
            (-97.793186, 30.547194),
            (-97.7892304, 30.5487087),
            (-97.7892304, 30.5497087),
            (-97.793186, 30.547194)
        ])
    
    if gdf_s_flood_merge_ar.iloc[0]['geometry'] is None:
        gdf_s_flood_merge_ar.at[gdf_s_flood_merge_ar.index[0], 'geometry'] = geometry_fake_area
        gdf_s_flood_merge_ar['is_real'] = 0
        gdf_s_flood_merge_ar['is_real'] = gdf_s_flood_merge_ar['is_real'].astype(int)
        
    # -- If empty, create a AGOL placeholder for road lines
    if gdf_s_flood_road_trim_ln.empty:
        
        geometry_fake_line = MultiLineString([[
            (-97.793186, 30.547194),
            (-97.7892304, 30.5487087)]])
    
        # Define placeholder attributes
        dict_empty_road_data = {
            'osm_id': [-1],
            'fclass': ['unknown'],
            'name': ["This placeholder when there is no flooding that allows AGOL to still load the layer"],
            'ref': [''],
            'road_id': [-1],
            'nextgen_id': [-1],
            'min_flood_flow': [-1],
            'max_flow': [-1],
            'model_run_time': [str_model_run_time],
            'length_ft': [0],
            'geometry': [geometry_fake_line]
        }
        
        gdf_s_flood_road_trim_ln = gpd.GeoDataFrame(dict_empty_road_data, crs="EPSG:4326")
        
    # -- If empty, create a AGOL placeholder for road lines
    if gdf_s_flood_road_nav_ln.empty:
        
        geometry_fake_line = MultiLineString([[
            (-97.793186, 30.547194),
            (-97.7892304, 30.5487087)]])
    
        # Define placeholder attributes
        dict_empty_road_data = {
            'osm_id': [-1],
            'fclass': ['unknown'],
            'name': ["This placeholder when there is no flooding that allows AGOL to still load the layer"],
            'ref': [''],
            'road_id': [-1],
            'nextgen_id': [-1],
            'min_flood_flow': [-1],
            'max_flow': [-1],
            'model_run_time': [str_model_run_time],
            'length_ft': [0],
            'geometry': [geometry_fake_line]
        }
        
        gdf_s_flood_road_nav_ln = gpd.GeoDataFrame(dict_empty_road_data, crs="EPSG:4326")
        
    # -- If empty, create a AGOL placeholder for bridge warning points
    if gdf_s_bridge_warning_pnt.empty:
        
        geometry_fake_point = Point(-97.793186, 30.547194)
    
        # Define placeholder attributes
        dict_empty_bridge_data = {
            'BRDG_ID': ['-1'],
            'uuid_bridge': ['-1'],
            'min_low_ch': [None],
            'min_ground': [None],
            'min_overtop': [None],
            'name': ["This placeholder when there is no flooding that allows AGOL to still load the layer"],
            'ref': [''],
            'nhd_name': [''],
            'model_run_time': [str_model_run_time],
            'max_wse': [None],
            'min_dist_to_low_ch': [100],
            'is_overtop': ['0'],
            'depth_array': [[ ]],
            'url': [''],
            'warn_class': ['low'],
            'geometry': [geometry_fake_point]
        }
        
        gdf_s_bridge_warning_pnt = gpd.GeoDataFrame(dict_empty_bridge_data, crs="EPSG:4326")
    
    # --- Prepare layers for lean TxDOT export ---
    columns_to_keep_road_nav = ['geometry', 'name', 'ref', 'fclass', 'model_run_time']
    gdf_s_flood_road_nav_ln = gdf_s_flood_road_nav_ln[columns_to_keep_road_nav]
    
    columns_to_keep_road_trim = ['geometry', 'name', 'ref', 'fclass', 'model_run_time', 'length_ft']
    gdf_s_flood_road_trim_ln = gdf_s_flood_road_trim_ln[columns_to_keep_road_trim]
    
    # Prepare prepare bridge worning points for geoJSON
    gdf_s_bridge_warning_pnt['warn_class'] = gdf_s_bridge_warning_pnt.apply(fn_assign_warn_class, axis=1)
    columns_to_keep_bridge = ['geometry', 'warn_class', 'BRDG_ID', 'name', 'ref', 'nhd_name', 'min_dist_to_low_ch', 'model_run_time', 'url']
    gdf_s_bridge_warning_pnt = gdf_s_bridge_warning_pnt[columns_to_keep_bridge]

    if 'local_results' in config:
        # --- Write the bridge points ---
        ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
        model_runtime = datetime.datetime.fromisoformat(ts).strftime("%Y%m%d%H%M")
        local_output_folder = config['local_results'].get('output_folder','/output')

        str_bridge_pnt_key = f"{local_output_folder}/{model_runtime}_bridge_warning_pnts.geojson"
        fn_write_gdf_to_file(gdf_s_bridge_warning_pnt, str_bridge_pnt_key)
        #str_bridge_pnt_esri_key = f"{local_output_folder}bridge_warning_pnts_esrijson.json"
        #fn_write_gdf_to_file_esrijson(gdf_s_bridge_warning_pnt, str_bridge_pnt_esri_key)
        
        # --- Write the navigation road lines ---
        str_road_nav_ln_key = f"{local_output_folder}/{model_runtime}_flood_road_nav_ln.geojson"
        fn_write_gdf_to_file(gdf_s_flood_road_nav_ln, str_road_nav_ln_key)
        #str_road_nav_ln_esri_key = f"{local_output_folder}/{model_runtime}_flood_road_nav_ln_esrijson.json"
        #fn_write_gdf_to_file_esrijson(gdf_s_flood_road_nav_ln, str_road_nav_ln_esri_key)
        
        # --- Write the trimmed road lines ---
        str_road_trim_ln_key = f"{local_output_folder}/{model_runtime}_flood_road_trim_ln.geojson"
        fn_write_gdf_to_file(gdf_s_flood_road_trim_ln, str_road_trim_ln_key)
        #str_road_trim_ln_esri_key = f"{local_output_folder}/{model_runtime}_flood_road_trim_ln_esrijson.json"
        #fn_write_gdf_to_file_esrijson(gdf_s_flood_road_trim_ln, str_road_trim_ln_esri_key)
        
        # --- Write the flood polygons ---
        str_flood_ar_key = f"{local_output_folder}/{model_runtime}_flood_ar.geojson"
        fn_write_gdf_to_file(gdf_s_flood_merge_ar, str_flood_ar_key)
        #str_flood_ar_esri_key = f"{local_output_folder}/{model_runtime}_flood_ar_esrijson.json"
        #fn_write_gdf_to_file_esrijson(gdf_s_flood_merge_ar, str_flood_ar_esri_key)
    
    if 'write_to_s3' in config:
        # --- Write the bridge points ---
        str_s3_bridge_pnt_key = f"{str_publish_sub_folder}bridge_warning_pnts.geojson"
        fn_write_gdf_to_s3(gdf_s_bridge_warning_pnt, str_bucket_name, str_s3_bridge_pnt_key)
        #str_s3_bridge_pnt_esri_key = f"{str_publish_sub_folder}bridge_warning_pnts_esrijson.json"
        #fn_write_gdf_to_s3_esrijson(gdf_s_bridge_warning_pnt, str_bucket_name, str_s3_bridge_pnt_esri_key)
        
        # --- Write the navigation road lines ---
        str_s3_road_nav_ln_key = f"{str_publish_sub_folder}flood_road_nav_ln.geojson"
        fn_write_gdf_to_s3(gdf_s_flood_road_nav_ln, str_bucket_name, str_s3_road_nav_ln_key)
        #str_s3_road_nav_ln_esri_key = f"{str_publish_sub_folder}flood_road_nav_ln_esrijson.json"
        #fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_nav_ln, str_bucket_name, str_s3_road_nav_ln_esri_key)
        
        # --- Write the trimmed road lines ---
        str_s3_road_trim_ln_key = f"{str_publish_sub_folder}flood_road_trim_ln.geojson"
        fn_write_gdf_to_s3(gdf_s_flood_road_trim_ln, str_bucket_name, str_s3_road_trim_ln_key)
        #str_s3_road_trim_ln_esri_key = f"{str_publish_sub_folder}flood_road_trim_ln_esrijson.json"
        #fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_trim_ln, str_bucket_name, str_s3_road_trim_ln_esri_key)
        
        # --- Write the flood polygons ---
        str_s3_flood_ar_key = f"{str_publish_sub_folder}flood_ar.geojson"
        fn_write_gdf_to_s3(gdf_s_flood_merge_ar, str_bucket_name, str_s3_flood_ar_key)
        #str_s3_flood_ar_esri_key = f"{str_publish_sub_folder}flood_ar_esrijson.json"
        #fn_write_gdf_to_s3_esrijson(gdf_s_flood_merge_ar, str_bucket_name, str_s3_flood_ar_esri_key)
# .........................................................


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':

    flt_start_run = time.time()
    
    parser = argparse.ArgumentParser(description='========= PUSH FAST LAYERS TO S3 =========')
    
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

    fn_push_to_s3(str_config_file_path, b_print_output)

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)
    
    print('Compute Time: ' + str(time_pass))
 #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~