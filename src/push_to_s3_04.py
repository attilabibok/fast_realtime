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
import argparse
from shapely.geometry import MultiLineString, Point, Polygon

import time
import datetime
import warnings
from utils import (
    FASTConfig,
    load_config,
    resolve_db_credentials,
    fn_get_geodataframe_from_postgresql,
    fn_write_gdf_to_file,
    fn_write_gdf_to_s3,
    fn_write_gdf_to_s3_esrijson
)

# ************************************************************


# ----------------------
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
def fn_push_to_s3(cfg: FASTConfig, b_print_output: bool):
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
        print("  ---[r] PRINT OUTPUT: " + str(b_print_output))
        print("===================================================================")
    else:
        print("Step 4: Uploading FAST Layers to S3")

    db_params = resolve_db_credentials(cfg.database)

    str_publish_sub_folder = ""
    if cfg.write_to_s3:

        # Handle optional publish_sub_folder
        str_publish_sub_folder = cfg.write_to_s3.publish_sub_folder.strip()
        if str_publish_sub_folder and not str_publish_sub_folder.endswith("/"):
            str_publish_sub_folder += "/"
    else:
        warnings.warn("Missing [write_to_s3] section in config file", stacklevel=2)

    # table names in PostgreSQL
    str_bridge_table_name = "s_bridge_warning_pnt"
    # str_road_nav_table_name = "s_flood_road_ln"
    str_road_table_name = "s_flood_road_trim_ln"
    str_inundation_table_name = "s_flood_merge_ar"

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

    # # --- Prepare layers for lean TxDOT export ---
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

    if cfg.local_results:
        # --- Write the bridge points ---
        ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
        model_runtime = datetime.datetime.fromisoformat(ts).strftime("%Y%m%d%H%M")
        local_output_folder = cfg.local_results.output_folder

        str_bridge_pnt_key = (
            f"{local_output_folder}/{model_runtime}_bridge_warning_pnts.geojson"
        )
        fn_write_gdf_to_file(gdf_s_bridge_warning_pnt, str_bridge_pnt_key)
        # str_bridge_pnt_esri_key = f"{local_output_folder}bridge_warning_pnts_esrijson.json"
        # fn_write_gdf_to_file_esrijson(gdf_s_bridge_warning_pnt, str_bridge_pnt_esri_key)

        # --- Write the trimmed road lines ---
        str_road_trim_ln_key = (
            f"{local_output_folder}/{model_runtime}_flood_road_trim_ln.geojson"
        )
        fn_write_gdf_to_file(gdf_s_flood_road_trim_ln, str_road_trim_ln_key)
        # str_road_trim_ln_esri_key = f"{local_output_folder}/{model_runtime}_flood_road_trim_ln_esrijson.json"
        # fn_write_gdf_to_file_esrijson(gdf_s_flood_road_trim_ln, str_road_trim_ln_esri_key)

        # --- Write the flood polygons ---
        str_flood_ar_key = f"{local_output_folder}/{model_runtime}_flood_ar.geojson"
        fn_write_gdf_to_file(gdf_s_flood_merge_ar, str_flood_ar_key)
        # str_flood_ar_esri_key = f"{local_output_folder}/{model_runtime}_flood_ar_esrijson.json"
        # fn_write_gdf_to_file_esrijson(gdf_s_flood_merge_ar, str_flood_ar_esri_key)

    if cfg.write_to_s3:
        # --- Write the bridge points ---
        if cfg.write_to_s3.publish_live:
            str_s3_bridge_pnt_key = f"{str_publish_sub_folder}bridge_warning_pnts.geojson"
            fn_write_gdf_to_s3(
                gdf_s_bridge_warning_pnt,
                cfg.write_to_s3.publish_bucket,
                str_s3_bridge_pnt_key,
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_bridge_pnt_esri_key = f"{str_publish_sub_folder}bridge_warning_pnts_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_bridge_warning_pnt, cfg.write_to_s3.publish_bucket, str_s3_bridge_pnt_esri_key)

        if cfg.write_to_s3.publish_historic:
            ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
            model_runtime = datetime.datetime.fromisoformat(ts).strftime("%Y%m%d%H%M")

            str_s3_bridge_pnt_key = (
                f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_bridge_warning_pnts.geojson"
            )
            fn_write_gdf_to_s3(
                gdf_s_bridge_warning_pnt,
                cfg.write_to_s3.publish_historic_bucket,
                str_s3_bridge_pnt_key,
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_bridge_pnt_esri_key = f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_bridge_warning_pnts_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_bridge_warning_pnt, cfg.write_to_s3.publish_bucket, str_s3_bridge_pnt_esri_key)


        # --- Write the trimmed road lines ---
        if cfg.write_to_s3.publish_live:
            str_s3_road_trim_ln_key = f"{str_publish_sub_folder}flood_road_trim_ln.geojson"
            fn_write_gdf_to_s3(
                gdf_s_flood_road_trim_ln,
                cfg.write_to_s3.publish_bucket,
                str_s3_road_trim_ln_key,
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_road_trim_ln_esri_key = f"{cfg.write_to_s3.publish_sub_folder}flood_road_trim_ln_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_trim_ln,  cfg.write_to_s3.publish_bucket, str_s3_road_trim_ln_esri_key)


        if cfg.write_to_s3.publish_historic:
            ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
            model_runtime = datetime.datetime.fromisoformat(ts).strftime("%Y%m%d%H%M")
            str_s3_road_trim_ln_key = (
                f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_flood_road_trim_ln.geojson"
            )
            fn_write_gdf_to_s3(
                gdf_s_flood_road_trim_ln,
                cfg.write_to_s3.publish_historic_bucket,
                str_s3_road_trim_ln_key,
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_road_trim_ln_esri_key = f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_flood_road_trim_ln_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_flood_road_trim_ln,  cfg.write_to_s3.publish_historic_bucket, str_s3_road_trim_ln_esri_key)

        # --- Write the flood polygons ---
        if cfg.write_to_s3.publish_live:
            str_s3_flood_ar_key = f"{str_publish_sub_folder}flood_ar.geojson"
            fn_write_gdf_to_s3(
                gdf_s_flood_merge_ar, cfg.write_to_s3.publish_bucket, str_s3_flood_ar_key
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_flood_ar_esri_key = f"{str_publish_sub_folder}flood_ar_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_flood_merge_ar, cfg.write_to_s3.publish_bucket, str_s3_flood_ar_esri_key)
    
        if cfg.write_to_s3.publish_historic:
            ts = gdf_s_bridge_warning_pnt.loc[0, "model_run_time"]
            model_runtime = datetime.datetime.fromisoformat(ts).strftime("%Y%m%d%H%M")
            str_s3_flood_ar_key = (
                f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_flood_ar.geojson"
            )
            fn_write_gdf_to_s3(
                gdf_s_flood_merge_ar,
                cfg.write_to_s3.publish_historic_bucket,
                str_s3_flood_ar_key,
            )
            if cfg.write_to_s3.publish_esri_json:
                str_s3_flood_ar_esri_key = f"{cfg.write_to_s3.publish_historic_sub_folder}/{model_runtime}_flood_ar_esrijson.json"
                fn_write_gdf_to_s3_esrijson(gdf_s_flood_merge_ar, cfg.write_to_s3.publish_historic_bucket, str_s3_flood_ar_esri_key)


# .........................................................


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":

    flt_start_run = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)

    fn_push_to_s3(cfg, b_print_output=not args.quiet)

    flt_end_run = time.time()
    flt_time_pass = (flt_end_run - flt_start_run) // 1
    time_pass = datetime.timedelta(seconds=flt_time_pass)

    print("Compute Time: " + str(time_pass))
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
