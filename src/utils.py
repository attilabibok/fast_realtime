from pathlib import Path
from typing import Optional, Union, Any, Dict, List, Optional
from aiobotocore.session import get_session
import math
import configparser
import json
import psycopg2
import yaml
import re
from pydantic import BaseModel, Field, field_validator
from configparser import ConfigParser
from pydantic_settings import BaseSettings, SettingsConfigDict
import pandas as pd
from datetime import datetime, timezone
from shapely.geometry import Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon
from shapely.geometry.base import BaseGeometry
from geopandas import GeoDataFrame
import geopandas as gpd
import esrijson
import logging

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
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
    url: Optional[str] = None
    download_dir: str
    download_filename: str = 'valid_comids_texas_streamflow.nc'
    force: bool = False
    cleanup_after_load: bool = False
    parameter: str = "streamflow"
    workflow_id: str = Field(default="default")
    input_schema: str = "public"
    # Timestamp filter
    exclude_column_indexes: Optional[list[int]] = Field(None, description="What column indexes to exclude from the raw streamflow input")

    @field_validator("exclude_column_indexes", mode="before")
    def parse_exclude_indexes(cls, v: Union[str, int, list[int], None]):
        if v is None:
            return None
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            # allow "1,2,5" or "1 2 5"
            parts = [p for p in v.replace(",", " ").split() if p]
            return [int(p) for p in parts]
        raise TypeError(f"Unsupported type for exclude_column_indexes: {type(v)}")

class FlowFromNWMConfig(BaseModel):
    texas_feature_id_list: str = Field(..., alias="texas_faeture_id_list")
    force: bool = False
    workflow_id: str = Field(default="default")
    input_schema: str = "public"


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


## ESRI STUFF


def _to_epoch_ms(dt: pd.Timestamp) -> Optional[int]:
    if pd.isna(dt):
        return None
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    else:
        dt = dt.tz_convert("UTC")
    return int((dt - EPOCH).total_seconds() * 1000)

def _esri_geometry_type_from_example(geom: BaseGeometry) -> str:
    if isinstance(geom, Point):
        return "esriGeometryPoint"
    if isinstance(geom, (LineString, MultiLineString)):
        return "esriGeometryPolyline"
    if isinstance(geom, (Polygon, MultiPolygon)):
        return "esriGeometryPolygon"
    if isinstance(geom, MultiPoint):
        return "esriGeometryMultipoint"
    raise ValueError(f"Unsupported geometry type: {type(geom)}")

def _geom_to_esri(geom: BaseGeometry) -> Optional[Dict[str, Any]]:
    if geom is None or geom.is_empty:
        return None

    if isinstance(geom, Point):
        return {"x": geom.x, "y": geom.y}

    if isinstance(geom, LineString):
        return {"paths": [list(map(list, geom.coords))]}

    if isinstance(geom, MultiLineString):
        return {"paths": [list(map(list, ls.coords)) for ls in geom.geoms]}

    if isinstance(geom, Polygon):
        # Exterior ring, then interior rings (holes). ArcGIS accepts ring orientation;
        # holes should be opposite orientation from shell.
        rings = [list(map(list, geom.exterior.coords))]
        rings.extend([list(map(list, r.coords)) for r in geom.interiors])
        return {"rings": rings}

    if isinstance(geom, MultiPolygon):
        rings: List[List[List[float]]] = []
        for poly in geom.geoms:
            rings.append(list(map(list, poly.exterior.coords)))
            rings.extend([list(map(list, r.coords)) for r in poly.interiors])
        return {"rings": rings}

    if isinstance(geom, MultiPoint):
        return {"points": [[p.x, p.y] for p in geom.geoms]}

    return None

def _esri_field_type(dtype: Any) -> str:
    # Map pandas dtypes to Esri field types (keep it simple & practical).
    if pd.api.types.is_integer_dtype(dtype):
        # Choose OID separately; here general integer -> esriFieldTypeInteger (32-bit)
        return "esriFieldTypeInteger"
    if pd.api.types.is_float_dtype(dtype):
        return "esriFieldTypeDouble"
    if pd.api.types.is_bool_dtype(dtype):
        return "esriFieldTypeSmallInteger"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "esriFieldTypeDate"  # epoch ms
    return "esriFieldTypeString"

def gdf_to_esri_featureset(gdf: GeoDataFrame,
                           objectid_field: str = "OBJECTID",
                           wkid: int = 4326) -> Dict[str, Any]:
    if gdf.empty:
        # Minimal empty FeatureSet
        return {
            "objectIdFieldName": objectid_field,
            "geometryType": "esriGeometryPoint",
            "spatialReference": {"wkid": wkid},
            "fields": [{"name": objectid_field, "type": "esriFieldTypeOID", "alias": objectid_field}],
            "features": []
        }

    # Ensure WGS84 unless you intentionally want something else
    if gdf.crs is not None and gdf.crs.to_epsg() != wkid:
        gdf = gdf.to_crs(epsg=wkid)

    # Guarantee an integer OBJECTID
    if objectid_field not in gdf.columns:
        # avoid collision with user columns
        base = 1
        series = pd.Series(range(base, base + len(gdf)), index=gdf.index, dtype="int64")
        gdf = gdf.assign(**{objectid_field: series})
    else:
        # Coerce to int; fill NaN
        tmp = gdf[objectid_field].copy()
        tmp = tmp.fillna(pd.Series(range(1, 1 + len(tmp)), index=gdf.index))
        gdf[objectid_field] = tmp.astype("int64")

    # Determine geometry type from the first non-empty geometry
    example_geom = next((g for g in gdf.geometry if g is not None and not g.is_empty), None)
    if example_geom is None:
        geometry_type = "esriGeometryPoint"
    else:
        geometry_type = _esri_geometry_type_from_example(example_geom)

    # Build fields schema
    fields = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        if col == objectid_field:
            fields.append({"name": objectid_field, "type": "esriFieldTypeOID", "alias": objectid_field})
            continue

        ftype = _esri_field_type(gdf[col].dtype)
        field_def: Dict[str, Any] = {"name": col, "type": ftype, "alias": col}
        if ftype == "esriFieldTypeString":
            # rough length cap—AGOL needs a length for strings
            max_len = int(min(255, max((len(str(v)) for v in gdf[col].dropna().unique()), default=50)))
            field_def["length"] = max(1, max_len)
        fields.append(field_def)

    # Build features array
    feats = []
    for idx, row in gdf.iterrows():
        geom = row[gdf.geometry.name]
        esri_geom = _geom_to_esri(geom) if isinstance(geom, BaseGeometry) else None

        attrs = {}
        for col in gdf.columns:
            if col == gdf.geometry.name:
                continue
            val = row[col]
            if pd.api.types.is_datetime64_any_dtype(gdf[col].dtype):
                if pd.isna(val):
                    attrs[col] = None
                else:
                    # Convert to epoch ms UTC
                    attrs[col] = _to_epoch_ms(pd.to_datetime(val))
            else:
                # JSON-serializable best-effort
                if pd.isna(val):
                    attrs[col] = None
                else:
                    attrs[col] = val.item() if hasattr(val, "item") else val

        feats.append({"attributes": attrs, "geometry": esri_geom})

    fs = {
        "objectIdFieldName": objectid_field,
        "geometryType": geometry_type,
        "spatialReference": {"wkid": wkid},
        "fields": fields,
        "features": feats,
    }
    return fs


#### ESRI STUFF ends

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
async def fn_write_gdf_to_s3_esri_featureset(gdf, str_bucket_name: str, str_s3_key: str):
    """
    Writes a proper Esri FeatureSet (Feature Collection) JSON to S3.
    Suitable for ArcGIS Online 'Add layer from web' (Feature Collection) or ArcGIS JS API.
    """

    # Ensure CRS and schema, convert to Esri FeatureSet
    fs_dict = gdf_to_esri_featureset(gdf, objectid_field="OBJECTID", wkid=4326)
    body = json.dumps(fs_dict, ensure_ascii=False).encode("utf-8")

    s3settings = S3APISettings()
    session = get_session()
    async with session.create_client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id=s3settings.access_key_id,
        aws_secret_access_key=s3settings.secret_access_key,
    ) as s3:
        await s3.put_object(
            Bucket=str_bucket_name,
            Key=str_s3_key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            CacheControl="no-cache",
        )


def fn_get_dataframe_from_postgresql(table: str, db: dict, workflow_id: str | None = "default") -> pd.DataFrame:
    conn = psycopg2.connect(**db)
    cur = conn.cursor()
    try:
        if workflow_id is not None:
            query = f"SELECT * FROM {table} WHERE workflow_id = %s"
            cur.execute(query, (workflow_id,))
        else:
            query = f"SELECT * FROM {table}"
            cur.execute(query)
        cur.execute(query, (workflow_id,))
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=colnames)
    finally:
        cur.close()
        conn.close()
