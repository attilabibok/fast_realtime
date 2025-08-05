# FAST-realtime update
# Script 04 - push_to_s3_04
#
#
# Created by: Andy Carter, PE
# Created - 2025.05.03
# Revised - 2025.06.06 -- Subfolder allowed on S3 -- publish_sub_folder
# Revised - 2025.06.13 -- Revised to Esri.json  - commented out
# Revised - 2025.07.26 -- Refactored for materialized views (A. Bibok)
# ************************************************************

# ************************************************************
import geopandas as gpd
import argparse
from shapely.geometry import MultiLineString, Point, Polygon
import os

import asyncio
import time
import datetime
import warnings

from utils import (
    FASTConfig,
    load_config,
    resolve_db_credentials,
    fn_run_sql_script,
    fn_get_geodataframe_from_postgresql,
    fn_write_gdf_to_s3,
    fn_write_gdf_to_file,
    fn_write_gdf_to_s3_esrijson,
)
import logging
logger = logging.getLogger(__name__)

# ************************************************************


# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist" % arg)
    else:
        # File exists so return the directory
        return arg


# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


# ----------------
def fn_str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in {"true", "t", "1"}:
        return True
    elif value.lower() in {"false", "f", "0"}:
        return False
    else:
        raise argparse.ArgumentTypeError(f"Boolean value expected. Got '{value}'.")


# ----------------


# ----------------
def fn_assign_warn_class(row):
    if row["is_overtop"] == 1:
        return "overtopped"
    elif row["min_dist_to_low_ch"] < 0.5:
        return "critical"
    elif 0.5 <= row["min_dist_to_low_ch"] < 2:
        return "high"
    elif 2 <= row["min_dist_to_low_ch"] < 5:
        return "moderate"
    else:
        return "low"


# ----------------


# .........................................................
async def fn_merged_view(cfg: FASTConfig, b_print_output: bool = False):
    # suppress all warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    if b_print_output:
        logger.info("+=================================================================+")
        logger.info("|                   PUSH FAST LAYERS TO S3                        |")
        logger.info("|                Created by Andy Carter, PE of                    |")
        logger.info("|             Center for Water and the Environment                |")
        logger.info("|                 University of Texas at Austin                   |")
        logger.info("+-----------------------------------------------------------------+")
        logger.info("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        logger.info("===================================================================")
    else:
        logger.info("Step 4: Uploading FAST Layers to S3")

    # --- Read variables from config.ini ---

    db_params = resolve_db_credentials(cfg.database)

    sql_file_path = cfg.merged_view.sql_file_path
    if not sql_file_path:
        logger.error("  !! SQL file path not provided in config")
        return "error"

    logger.debug(f"  -- SQL file: {sql_file_path}")

    status = "error"
    try:
        db_config = resolve_db_credentials(cfg.database)
        result = fn_run_sql_script(db_config, sql_file_path)
        status = result  # 'success', 'timeout', or 'error'
    except Exception as e:
        logger.error(f"  !! SQL execution failed: {e}")
        status = "error"

    # If the merged view is created, extract the results and publish

    # table names in PostgreSQL
    str_bridge_table_name = "mv_bridge_warning_pnt_tx"
    # str_road_nav_table_name = "mv_flood_road_ln_tx"
    str_road_table_name = "mv_flood_road_trim_ln_tx"
    str_inundation_table_name = "mv_flood_merge_tx"

    gdf_s_bridge_warning_pnt = fn_get_geodataframe_from_postgresql(
        str_bridge_table_name, db_params, "geometry"
    )
    # gdf_s_flood_road_nav_ln = fn_get_geodataframe_from_postgresql(
    #     str_road_nav_table_name, db_params, "geometry"
    # )
    gdf_s_flood_road_trim_ln = fn_get_geodataframe_from_postgresql(
        str_road_table_name, db_params, "geometry"
    )
    gdf_s_flood_merge_ar = fn_get_geodataframe_from_postgresql(
        str_inundation_table_name, db_params, "geometry"
    )

    # Even if there are no polygons, this shold have one row with model_run_time
    str_model_run_time = gdf_s_flood_merge_ar.iloc[0]["model_run_time"]

    geometry_fake_area = Polygon(
        [
            (-97.793186, 30.547194),
            (-97.7892304, 30.5487087),
            (-97.7892304, 30.5497087),
            (-97.793186, 30.547194),
        ]
    )

    if gdf_s_flood_merge_ar.iloc[0]["geometry"] is None:
        gdf_s_flood_merge_ar.at[gdf_s_flood_merge_ar.index[0], "geometry"] = (
            geometry_fake_area
        )
        gdf_s_flood_merge_ar["is_real"] = 0
        gdf_s_flood_merge_ar["is_real"] = gdf_s_flood_merge_ar["is_real"].astype(int)

    # -- If empty, create a AGOL placeholder for road lines
    if gdf_s_flood_road_trim_ln.empty:

        geometry_fake_line = MultiLineString(
            [[(-97.793186, 30.547194), (-97.7892304, 30.5487087)]]
        )

        # Define placeholder attributes
        dict_empty_road_data = {
            "osm_id": [-1],
            "fclass": ["unknown"],
            "name": [
                "This placeholder when there is no flooding that allows AGOL to still load the layer"
            ],
            "ref": [""],
            "road_id": [-1],
            "nextgen_id": [-1],
            "min_flood_flow": [-1],
            "max_flow": [-1],
            "model_run_time": [str_model_run_time],
            "length_ft": [0],
            "geometry": [geometry_fake_line],
        }

        gdf_s_flood_road_trim_ln = gpd.GeoDataFrame(
            dict_empty_road_data, crs="EPSG:4326"
        )

    # -- If empty, create a AGOL placeholder for bridge warning points
    if gdf_s_bridge_warning_pnt.empty:

        geometry_fake_point = Point(-97.793186, 30.547194)

        # Define placeholder attributes
        dict_empty_bridge_data = {
            "BRDG_ID": ["-1"],
            "uuid_bridge": ["-1"],
            "min_low_ch": [None],
            "min_ground": [None],
            "min_overtop": [None],
            "name": [
                "This placeholder when there is no flooding that allows AGOL to still load the layer"
            ],
            "ref": [""],
            "nhd_name": [""],
            "model_run_time": [str_model_run_time],
            "max_wse": [None],
            "min_dist_to_low_ch": [100],
            "is_overtop": ["0"],
            "depth_array": [[]],
            "url": [""],
            "warn_class": ["low"],
            "geometry": [geometry_fake_point],
        }

        gdf_s_bridge_warning_pnt = gpd.GeoDataFrame(
            dict_empty_bridge_data, crs="EPSG:4326"
        )

    # --- Prepare layers for lean TxDOT export ---
    # columns_to_keep_road_nav = ["geometry", "name", "ref", "fclass", "model_run_time"]
    # gdf_s_flood_road_nav_ln = gdf_s_flood_road_nav_ln[columns_to_keep_road_nav]

    columns_to_keep_road_trim = [
        "geometry",
        "name",
        "ref",
        "fclass",
        "model_run_time",
        "length_ft",
    ]
    gdf_s_flood_road_trim_ln = gdf_s_flood_road_trim_ln[columns_to_keep_road_trim]

    # Prepare prepare bridge worning points for geoJSON
    gdf_s_bridge_warning_pnt["warn_class"] = gdf_s_bridge_warning_pnt.apply(
        fn_assign_warn_class, axis=1
    )
    columns_to_keep_bridge = [
        "geometry",
        "warn_class",
        "BRDG_ID",
        "name",
        "ref",
        "nhd_name",
        "min_dist_to_low_ch",
        "model_run_time",
        "url",
    ]
    gdf_s_bridge_warning_pnt = gdf_s_bridge_warning_pnt[columns_to_keep_bridge]

    # Get model runtime for sure. do not rely on non-empty results.
    # db_conn_info = resolve_db_credentials(cfg.database)
    # df_current = fn_get_dataframe_from_postgresql('t_current_forecast', db_conn_info)
    # model_run_time = df_current.iloc[0]['model_run_time'].tz_localize("UTC")
    # str_model_runtime = model_run_time.strftime("%Y%m%d%H%M")
    should_publish_historic = False

    if cfg.merged_view is not None:
        if cfg.merged_view.s3_output and cfg.merged_view.s3_output.publish_historic:
            should_publish_historic = True
        if cfg.merged_view.local_output and cfg.merged_view.local_output.publish_historic:
            should_publish_historic = True

    if cfg.write_to_s3 and cfg.write_to_s3.publish_historic:
        should_publish_historic = True

    if cfg.local_results and cfg.local_results.publish_historic:
        should_publish_historic = True

    if should_publish_historic:
        if gdf_s_bridge_warning_pnt.empty:
            raise ValueError(
                "Bridge warning table is empty! Cannot deduct model runtime...."
            )
        else:
            ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
            str_model_runtime = datetime.datetime.fromisoformat(ts).strftime(
                "%Y%m%d%H%M"
            )

    if cfg.merged_view.local_output:
        if cfg.merged_view.local_output.publish_historic:  # historic results
            local_output_folder = cfg.merged_view.local_output.output_folder_historic
            if cfg.merged_view.local_output.publish_bridges:
                # --- Write the bridge points ---
                str_bridge_pnt_key = f"{local_output_folder}/{str_model_runtime}_bridge_warning_pnts.geojson"
                fn_write_gdf_to_file(gdf_s_bridge_warning_pnt, str_bridge_pnt_key)
                # str_bridge_pnt_esri_key = f"{local_output_folder}bridge_warning_pnts_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_bridge_warning_pnt, str_bridge_pnt_esri_key)

            if cfg.merged_view.local_output.publish_roads:
                # --- Write the trimmed road lines ---
                str_road_trim_ln_key = f"{local_output_folder}/{str_model_runtime}_flood_road_trim_ln.geojson"
                fn_write_gdf_to_file(gdf_s_flood_road_trim_ln, str_road_trim_ln_key)
                # str_road_trim_ln_esri_key = f"{local_output_folder}/{str_model_runtime}_flood_road_trim_ln_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_flood_road_trim_ln, str_road_trim_ln_esri_key)

            if cfg.merged_view.local_output.publish_inundation:
                # --- Write the flood polygons ---
                str_flood_ar_key = (
                    f"{local_output_folder}/{str_model_runtime}_flood_ar.geojson"
                )
                fn_write_gdf_to_file(gdf_s_flood_merge_ar, str_flood_ar_key)
                # str_flood_ar_esri_key = f"{local_output_folder}/{str_model_runtime}_flood_ar_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_flood_merge_ar, str_flood_ar_esri_key)

        if cfg.merged_view.local_output.publish_live:  # live results
            local_output_folder = cfg.merged_view.local_output.output_folder
            if cfg.merged_view.local_output.publish_bridges:
                # --- Write the bridge points ---
                str_bridge_pnt_key = (
                    f"{local_output_folder}/bridge_warning_pnts.geojson"
                )
                fn_write_gdf_to_file(gdf_s_bridge_warning_pnt, str_bridge_pnt_key)
                # str_bridge_pnt_esri_key = f"{local_output_folder}bridge_warning_pnts_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_bridge_warning_pnt, str_bridge_pnt_esri_key)

            if cfg.merged_view.local_output.publish_roads:
                # --- Write the trimmed road lines ---
                str_road_trim_ln_key = (
                    f"{local_output_folder}/flood_road_trim_ln.geojson"
                )
                fn_write_gdf_to_file(gdf_s_flood_road_trim_ln, str_road_trim_ln_key)
                # str_road_trim_ln_esri_key = f"{local_output_folder}/{str_model_runtime}_flood_road_trim_ln_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_flood_road_trim_ln, str_road_trim_ln_esri_key)

            if cfg.merged_view.local_output.publish_inundation:
                # --- Write the flood polygons ---
                str_flood_ar_key = f"{local_output_folder}/flood_ar.geojson"
                fn_write_gdf_to_file(gdf_s_flood_merge_ar, str_flood_ar_key)
                # str_flood_ar_esri_key = f"{local_output_folder}/{str_model_runtime}_flood_ar_esrijson.json"
                # fn_write_gdf_to_file_esrijson(gdf_s_flood_merge_ar, str_flood_ar_esri_key)

    s3_tasks = []

    if cfg.merged_view and cfg.merged_view.s3_output:
        s3 = cfg.merged_view.s3_output

        # ---------- HISTORIC ----------
        if s3.publish_historic:
            sub = f"{s3.publish_historic_sub_folder}/{str_model_runtime}_"

            if s3.publish_bridges:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_bridge_warning_pnt, s3.publish_bucket, f"{sub}bridge_warning_pnts.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_bridge_warning_pnt, s3.publish_bucket, f"{sub}bridge_warning_pnts_esrijson.json"))

            if s3.publish_roads:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_flood_road_trim_ln, s3.publish_bucket, f"{sub}flood_road_trim_ln.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_trim_ln, s3.publish_bucket, f"{sub}flood_road_trim_ln_esrijson.json"))

            if s3.publish_inundation:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_flood_merge_ar, s3.publish_bucket, f"{sub}flood_ar.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_flood_merge_ar, s3.publish_bucket, f"{sub}flood_ar_esrijson.json"))

        # ---------- LIVE ----------
        if s3.publish_live:
            sub = s3.publish_sub_folder.strip()
            if sub and not sub.endswith("/"):
                sub += "/"

            if s3.publish_bridges:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_bridge_warning_pnt, s3.publish_bucket, f"{sub}bridge_warning_pnts.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_bridge_warning_pnt, s3.publish_bucket, f"{sub}bridge_warning_pnts_esrijson.json"))

            if s3.publish_roads:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_flood_road_trim_ln, s3.publish_bucket, f"{sub}flood_road_trim_ln.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_trim_ln, s3.publish_bucket, f"{sub}flood_road_trim_ln_esrijson.json"))

            if s3.publish_inundation:
                s3_tasks.append(fn_write_gdf_to_s3(gdf_s_flood_merge_ar, s3.publish_bucket, f"{sub}flood_ar.geojson"))
                if s3.publish_esri_json:
                    s3_tasks.append(fn_write_gdf_to_s3_esrijson(gdf_s_flood_merge_ar, s3.publish_bucket, f"{sub}flood_ar_esrijson.json"))

    # 🔄 Run all S3 uploads concurrently
    await asyncio.gather(*s3_tasks)


# .........................................................


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":

    flt_start_run = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)

    asyncio.run(fn_merged_view(cfg, b_print_output=not args.quiet))

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)

    logger.info("Compute Time: " + str(time_pass))
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
