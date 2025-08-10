from pathlib import Path
from typing import Optional, Union
from aiobotocore.session import get_session
import configparser
import json
import psycopg2
import yaml
import re
from pydantic import BaseModel, Field
from configparser import ConfigParser
from pydantic_settings import BaseSettings, SettingsConfigDict

import geopandas as gpd
import esrijson
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class DatabaseConfig(BaseSettings):
    username: str
    password: Optional[str] = None  # resolved at runtime
    host: str
    port: int = 5432
    dbname: str

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")


class S3APISettings(BaseSettings):

    access_key_id: str = ""
    secret_access_key: str = ""
    model_config = SettingsConfigDict(
        env_prefix="FAST_S3_", env_file=".env", extra="ignore"
    )


class DownloadConfig(BaseModel):
    url: str
    download_dir: str
    force: bool = False
    cleanup_after_load: bool = False


class FlowFromNWMConfig(BaseModel):
    texas_feature_id_list: str = Field(..., alias="texas_faeture_id_list")
    force: bool = False


class WriteToS3Config(BaseModel):
    publish_live: bool = True
    publish_bucket: str = ""
    publish_sub_folder: str = ""
    publish_historic: bool = False
    publish_historic_bucket: str = ""
    publish_historic_sub_folder: str = ""

    # Enable or disable product outputs
    publish_roads: bool = True
    publish_bridges: bool = True
    publish_inundation: bool = True

    # Enable esrijson output
    publish_esri_json: bool = False


class LocalResultsConfig(BaseModel):
    publish_live: bool = True
    publish_historic: bool = True

    # output folders
    output_folder: Optional[str] = "./output"
    output_folder_historic: Optional[str] = "./output_hist"

    # Enable or disable product outputs
    publish_roads: bool = True
    publish_bridges: bool = True
    publish_inundation: bool = True

    # Enable esrijson output
    publish_esri_json: bool = False


class SQLConfig(BaseModel):
    sql_file_path: str = "sql/roadflood_create_dynamic_tables_big.sql"
    workflow_id: str = Field(default="default")
    # local_output: Optional[LocalResultsConfig] = None
    # s3_output: Optional[WriteToS3Config] = None


class MergedResultsConfig(BaseModel):
    sql_file_path: str = "sql/create_merged_materialized_view.sql"
    local_output: Optional[LocalResultsConfig] = None
    s3_output: Optional[WriteToS3Config] = None
    workflow_id: str = Field(default="default")


class BridgeWarningsConfig(BaseModel):
    enabled: bool = True


class FASTConfig(BaseModel):
    database: DatabaseConfig
    download: Optional[DownloadConfig] = None
    flow_from_nwm: Optional[FlowFromNWMConfig] = None
    sql: Optional[SQLConfig] = None
    bridge_warnings: BridgeWarningsConfig = Field(...)
    write_to_s3: Optional[WriteToS3Config] = None
    local_results: Optional[LocalResultsConfig] = None
    merged_view: Optional[MergedResultsConfig] = None



class TqdmToLogger:
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, message):
        message = message.strip()
        if message:
            self.logger.log(self.level, message)

    def flush(self):
        pass  # Required for file-like API

def merge_nested_dict(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge_nested_dict(base[key], value)
        else:
            base[key] = value


def dot_to_nested_dict(dot_dict: dict) -> dict:
    nested = {}
    for compound_key, value in dot_dict.items():
        keys = compound_key.split(".")
        d = nested
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value
    return nested


def load_ini_to_dict(path: Path) -> dict:
    parser = ConfigParser()
    parser.read(path)

    result = dot_to_nested_dict(parser.defaults())

    for section in parser.sections():
        section_nested = dot_to_nested_dict(dict(parser.items(section)))
        section_path = section.split(".")
        d = {}
        curr = d
        for key in section_path[:-1]:
            curr = curr.setdefault(key, {})
        curr[section_path[-1]] = section_nested

        merge_nested_dict(result, d)

    return result


def load_config(path: Union[str, Path]) -> FASTConfig:
    path = Path(path)
    with open(path, "r") as f:
        if path.suffix in [".yml", ".yaml"]:
            raw = yaml.safe_load(f)
        elif path.suffix == ".json":
            raw = json.load(f)
        elif path.suffix == ".ini":
            raw = load_ini_to_dict(path)
        else:
            raise ValueError(f"Unsupported config file type: {path.suffix}")
    return FASTConfig.model_validate(raw)


def convert_ini_to_json(ini_path: Union[str, Path]) -> dict:
    config = configparser.ConfigParser()
    config.read(ini_path)
    return {section: dict(config[section]) for section in config.sections()}


def resolve_db_credentials(cfg: DatabaseConfig) -> dict:
    return {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.username,
        "password": cfg.password,
        "dbname": cfg.dbname,
    }


def safe_identifier(value: str, name="workflow_id") -> str:
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", value):
        return value
    raise ValueError(f"Unsafe value for {name}: {value!r}")

def fn_run_sql_script(db_config: dict, sql_file_path: str, params: dict = None) -> str:
    try:
        conn = psycopg2.connect(**db_config)
        logger.debug("  -- Connected to the database")

        with open(sql_file_path, "r") as sql_file:
            sql_script = sql_file.read()

        cursor = conn.cursor()
        try:
            # converted_sql = re.sub(r":'workflow_id'", r"%(workflow_id)s", sql_script)
            workflow_id = safe_identifier((params or {}).get("workflow_id", "default")) # this si crucial to separate results from different sreamflow sources
            # cursor.execute(converted_sql, {"workflow_id": workflow_id})
            # Step 1: convert psql-style placeholders to psycopg2-style
            intermediate_sql = sql_script.replace(":'workflow_id'", "%(workflow_id)s")

            # Step 2: replace with actual value (quoted)
            converted_sql = intermediate_sql.replace("%(workflow_id)s", f"'{workflow_id}'")
            # converted_sql = sql_script.replace("%(workflow_id)s", f"'{workflow_id}'")
            cursor.execute(converted_sql)
            conn.commit()
            logger.info("  -- SQL script executed successfully")
            return "success"
        except psycopg2.errors.QueryCanceled:
            logger.error("  !! SQL query exceeded statement_timeout and was canceled")
            return "timeout"
        except Exception as e:
            logger.error(f"  !! SQL execution error: {e}")
            return "error"
    finally:
        if "cursor" in locals():
            cursor.close()
        if "conn" in locals():
            conn.close()



def fn_get_geodataframe_from_postgresql(
    table_name: str,
    db_params: dict,
    geom_col: str = "geometry",
    workflow_id: str | None = "default"
) -> gpd.GeoDataFrame:
    """
    Fetch a GeoDataFrame from a PostGIS table using psycopg2, with optional workflow_id filtering.

    Parameters:
        table_name (str): Name of the table in 'schema.table' or 'table' format.
        db_params (dict): Dictionary with keys: host, dbname, user, password, port.
        geom_col (str): Name of the geometry column.
        workflow_id (str | None): Optional workflow ID to filter results. If None, fetch all.

    Returns:
        GeoDataFrame: The queried spatial data.
    """
    connection = psycopg2.connect(
        host=db_params.get("host"),
        dbname=db_params.get("dbname"),
        user=db_params.get("user"),
        password=db_params.get("password"),
        port=db_params.get("port", "5432"),
    )

    try:
        if workflow_id is not None:
            sql = f"SELECT * FROM {table_name} WHERE workflow_id = %s"
            gdf = gpd.read_postgis(sql, con=connection, geom_col=geom_col, params=(workflow_id,))
        else:
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
    gdf = gdf.apply(
        lambda x: (
            x.dt.strftime("%Y-%m-%dT%H:%M:%S") if x.dtype == "datetime64[ns]" else x
        )
    )

    # Write to file as GeoJSON
    gdf.to_file(filepath, driver="GeoJSON")
    logger.info(f"  -- Saved to {filepath}")


# ----------------------


# ----------------------
async def fn_write_gdf_to_s3(gdf, str_bucket_name: str, str_s3_key: str):

    # Convert datetime columns
    gdf = gdf.apply(
        lambda x: x.dt.strftime("%Y-%m-%dT%H:%M:%S") if x.dtype == "datetime64[ns]" else x
    )

    # Convert to GeoJSON
    geojson_str = gdf.to_json()
    geojson_bytes = geojson_str.encode("utf-8")

    # Upload using aiobotocore
    s3settings = S3APISettings()
    session = get_session()

    async with session.create_client(
        "s3",
        # region_name="us-west-1",  # or wherever your bucket lives
        aws_access_key_id=s3settings.access_key_id,
        aws_secret_access_key=s3settings.secret_access_key,
    ) as s3:
        await s3.put_object(Bucket=str_bucket_name, Key=str_s3_key, Body=geojson_bytes)
        logger.info(f"  -- Uploaded to s3://{str_bucket_name}/{str_s3_key}")

# ----------------------
async def fn_write_gdf_to_s3_esrijson(gdf, str_bucket_name: str, str_s3_key: str):

    gdf = gdf.apply(lambda x: x.dt.strftime("%Y-%m-%dT%H:%M:%S") if x.dtype == "datetime64[ns]" else x)

    geojson_str = gdf.to_json()
    geojson_dict = json.loads(geojson_str)
    esri_json_str = esrijson.dumps(geojson_dict)
    esri_json_bytes = esri_json_str.encode("utf-8")

    s3settings = S3APISettings()
    session = get_session()

    async with session.create_client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id=s3settings.access_key_id,
        aws_secret_access_key=s3settings.secret_access_key,
    ) as s3:
        await s3.put_object(Bucket=str_bucket_name, Key=str_s3_key, Body=esri_json_bytes)
        logger.info(f"  -- Uploaded ESRI JSON to s3://{str_bucket_name}/{str_s3_key}")

# ----------------------



def fn_get_dataframe_from_postgresql(table: str, db: dict, workflow_id: str | None = "default") -> pd.DataFrame:
    conn = psycopg2.connect(**db)
    cur = conn.cursor()
    try:
        if workflow_id is not None:
            query = f"SELECT * FROM public.{table} WHERE workflow_id = %s"
            cur.execute(query, (workflow_id,))
        else:
            query = f"SELECT * FROM public.{table}"
            cur.execute(query)
        cur.execute(query, (workflow_id,))
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=colnames)
    finally:
        cur.close()
        conn.close()
