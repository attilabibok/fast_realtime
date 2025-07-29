# FAST-realtime update
# Script 03 - create_s_bridge_warning_pnt_03
#
#
# Created by: Andy Carter, PE
# Created - 2025.05.02
# ************************************************************

# ************************************************************
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import geopandas as gpd
import numpy as np
import ast

import argparse
import time
import datetime
import warnings

from utils import FASTConfig, load_config, resolve_db_credentials
# ************************************************************

# ------------

def fn_get_dataframe_from_postgresql(str_table_name, db_params):
    conn = psycopg2.connect(**db_params)
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


# ~~~~~~~~~~~~~~~~~~
def fn_get_geodataframe_from_postgresql(str_table_name,
                                        dict_db_params,
                                        str_geom_col='geometry'):
    # Create psycopg2 connection
    conn = psycopg2.connect(
        host=dict_db_params.get("db_host"),
        user=dict_db_params.get("db_user"),
        password=dict_db_params.get("db_password"),
        dbname=dict_db_params.get("db_name")
    )

    # Read GeoDataFrame using raw psycopg2 connection
    gdf = gpd.read_postgis(f"SELECT * FROM public.{str_table_name}", con=conn, geom_col=str_geom_col)
    
    conn.close()
    return gdf
# ~~~~~~~~~~~~~~~~~~


# -------------
def fn_interpolate_wse_from_flow(flow_array, list_rating_curve_str_or_list):
    """
    Interpolate WSE values from a list of flow values using the rating curve.

    Parameters:
        flow_array (list of float): List of flow values (e.g., from df['flow_array']).
        list_rating_curve_str_or_list (str or list): Rating curve as a string or list of (flow, wse) tuples.

    Returns:
        list of float: Interpolated WSE values (rounded to 1 decimal place) for each flow in flow_array.
    """
    # Parse string to list if necessary
    if isinstance(list_rating_curve_str_or_list, str):
        rating_curve = ast.literal_eval(list_rating_curve_str_or_list)
    else:
        rating_curve = list_rating_curve_str_or_list

    # Unzip into separate arrays
    curve_flows, curve_wses = zip(*rating_curve)

    # Interpolate
    interpolated_wses = np.interp(flow_array, curve_flows, curve_wses, left=np.nan, right=np.nan)

    # Round to one decimal place
    return [round(wse, 1) if not np.isnan(wse) else np.nan for wse in interpolated_wses]
# -------------


# ---------
def fn_max_wse_arrays(series_of_lists):
    """Element-wise max from a Series of equal-length lists"""
    return list(np.nanmax(np.array(series_of_lists.tolist()), axis=0))
# ---------


# -------------
def fn_replace_nan_with_min_ground(row):
    return [val if not np.isnan(val) else row['min_ground'] for val in row['wse_array']]
# -------------


# -------
def fn_calculate_depth_array(row):
    return [round(max(wse - row['min_ground'], 0), 1) for wse in row['wse_array']]
# -------


# .........................................................
def fn_create_s_bridge_warning_pnt(cfg: FASTConfig, b_print_output: bool):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    print(" ")
    if b_print_output:
        print("+=================================================================+")
        print("|                CREATE BRIDGE WARNING POINTS                     |")
        print("|                Created by Andy Carter, PE of                    |")
        print("|             Center for Water and the Environment                |")
        print("|                 University of Texas at Austin                   |")
        print("+-----------------------------------------------------------------+")
        print("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        print("===================================================================")
    else:
        print('Step 3: Creating bridge warning points')

 

    db_params = resolve_db_credentials(cfg.database)

    print('  -- Computing bridge points')
    df_rating_curves = fn_get_dataframe_from_postgresql('t_bridge_rating_curve', db_params)
    df_max_flow = fn_get_dataframe_from_postgresql('t_flow_per_nextgen', db_params)

    uuid_list = df_rating_curves['uuid_bridge'].dropna().unique().tolist()
    uuid_tuple = tuple(uuid_list) if len(uuid_list) != 1 else (uuid_list[0], uuid_list[0])

    with psycopg2.connect(**db_params) as conn:
        sql_query = """
            SELECT * FROM public.s_bridge_pnt
            WHERE uuid_bridge IN %s
        """
        gdf_flow_points = gpd.read_postgis(sql_query, conn, params=(uuid_tuple,), geom_col='geometry')

    df_rating_max_flow = df_rating_curves.merge(df_max_flow, on='nextgen_id', how='left')
    df_rating_max_flow = df_rating_max_flow[df_rating_max_flow['max_flow'] >= df_rating_max_flow['min_flow']]

    if len(df_rating_max_flow) > 0:
        df_rating_max_flow['wse_array'] = df_rating_max_flow.apply(
            lambda row: fn_interpolate_wse_from_flow(row['flow_array'], row['list_rating_curve']), axis=1)

        df_max_by_uuid = df_rating_max_flow.groupby('uuid_bridge', as_index=False).agg({
            'wse_array': fn_max_wse_arrays,
            'model_run_time': 'first'
        })
        df_max_by_uuid['max_wse'] = df_max_by_uuid['wse_array'].apply(lambda x: np.nanmax(x))
        gdf_flow_points = gdf_flow_points.merge(df_max_by_uuid, on='uuid_bridge', how='left')
        gdf_flow_points = gdf_flow_points[~gdf_flow_points['max_wse'].isna()]
        gdf_flow_points['min_dist_to_low_ch'] = (
            gdf_flow_points['min_low_ch'] - gdf_flow_points['max_wse']
        ).round(1)
        gdf_flow_points['is_overtop'] = (gdf_flow_points['max_wse'] >= gdf_flow_points['min_overtop']).astype(int)
        gdf_flow_points['wse_array'] = gdf_flow_points.apply(fn_replace_nan_with_min_ground, axis=1)
        gdf_flow_points['depth_array'] = gdf_flow_points.apply(fn_calculate_depth_array, axis=1)
        gdf_flow_points = gdf_flow_points.drop(columns=['wse_array'])
        gdf_flow_points['model_run_time'] = pd.to_datetime(
            gdf_flow_points['model_run_time']).dt.strftime('%Y-%m-%dT%H:%M:%S')
        gdf_flow_points['depth_array_str'] = gdf_flow_points['depth_array'].apply(
            lambda arr: ','.join(f"{x:.1f}" for x in arr))
        gdf_flow_points['url'] = (
            "https://bridges.txdot.kisters.cloud/xs/?uuid=" +
            gdf_flow_points['uuid_bridge'] +
            "&list_wse=" + gdf_flow_points['depth_array_str'] +
            "&first_utc_time=" + gdf_flow_points['model_run_time']
        )
        gdf_flow_points = gdf_flow_points.drop(columns=['depth_array_str'])
    else:
        print('  -- No bridge warnings to report')
        gdf_flow_points = gpd.GeoDataFrame(columns=[
            'geometry', 'BRDG_ID', 'uuid_bridge', 'min_low_ch', 'min_ground', 'min_overtop',
            'name', 'ref', 'nhd_name', 'model_run_time', 'max_wse', 'min_dist_to_low_ch',
            'is_overtop', 'depth_array', 'url'], geometry='geometry', crs='EPSG:4326')

    print('  -- Uploading bridge points to PostgreSQL')
    engine_url = (
        f"postgresql+psycopg2://{db_params['user']}:{db_params['password']}@{db_params['host']}/{db_params['dbname']}"
    )
    engine = create_engine(engine_url)
    with engine.connect() as conn:
        gdf_flow_points.to_postgis("s_bridge_warning_pnt", conn, if_exists='replace', index=False)
    print('  -- Bridge points successfully uploaded')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    start = time.time()
    fn_create_s_bridge_warning_pnt(cfg, b_print_output=not args.quiet)
    end = time.time()
    print(f"\nCompute Time: {datetime.timedelta(seconds=int(end - start))}")
 #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~