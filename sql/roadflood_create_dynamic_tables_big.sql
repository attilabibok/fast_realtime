-- SETTING A TIMEOUT FOR HEAVY QUERRIES
-- revised 2025.06.10
SET statement_timeout TO '3min';

-- Acquire an advisory lock to prevent concurrent executions
SELECT pg_advisory_lock(20250628);

-- ITEM #0
-- Establish flows per stream

DROP TABLE IF EXISTS t_flow_per_nextgen;

CREATE TABLE t_flow_per_nextgen AS
WITH unique_ids AS (
    SELECT DISTINCT nextgen_id::text AS nextgen_id
    FROM s_flood_inundation_ar
),
crosswalked AS (
    SELECT u.nextgen_id, x.feature_id
    FROM unique_ids u
    JOIN t_nextgen_to_nwm x ON u.nextgen_id = x.nextgen_id
),
flows_with_array AS (
    SELECT
        c.nextgen_id,
        f.feature_id,
        f.model_run_time,
        ARRAY[
            flow_t00, flow_t01, flow_t02, flow_t03, flow_t04, flow_t05,
            flow_t06, flow_t07, flow_t08, flow_t09, flow_t10, flow_t11,
            flow_t12, flow_t13, flow_t14, flow_t15, flow_t16, flow_t17
        ] AS flow_array
    FROM crosswalked c
    JOIN t_flow_forecast f ON c.feature_id = f.feature_id
)
SELECT
    nextgen_id,
    feature_id,
    model_run_time,
    flow_array,
    (
        SELECT MAX(val) FROM unnest(flow_array) AS val
    ) AS max_flow,
    (
        SELECT i - 1
        FROM generate_subscripts(flow_array, 1) AS i
        WHERE flow_array[i] = (
            SELECT MAX(val) FROM unnest(flow_array) AS val
        )
        LIMIT 1
    ) AS max_hour
FROM flows_with_array;

CREATE INDEX idx_t_flow_per_nextgen_nextgen_id ON t_flow_per_nextgen(nextgen_id);

/*
Method to comment out multiple rows
*/

/*
-- temporary fake flow for testing
UPDATE t_flow_per_nextgen
SET
   flow_array[1] = 100,
   flow_array[2] = 200,
   flow_array[3] = 300,
   flow_array[4] = 400,
   flow_array[5] = 500,
   flow_array[6] = 600,
   flow_array[7] = 4200,
   flow_array[8] = 1200,
   flow_array[9] = 800,
   flow_array[10] = 400,
   flow_array[11] = 100,
   flow_array[12] = 100,
   flow_array[13] = 100,
   flow_array[14] = 50,
   flow_array[15] = 50,
   flow_array[16] = 50,
   flow_array[17] = 50,
   flow_array[18] = 0,
   max_flow = 4200,
   max_hour = 7;
-- end temp
*/

-- ITEM #1
-- select the appropriate flood area polygons -- 29 seconds (11528 polys from 397k)
DROP TABLE IF EXISTS s_selected_flood_ar;

-- Composite index on nextgen_id and flow DESC helps with both filtering and ordering
CREATE INDEX IF NOT EXISTS idx_flood_inundation_ar_nextgen_flow
ON s_flood_inundation_ar(nextgen_id, flow DESC);

CREATE TABLE s_selected_flood_ar AS
SELECT DISTINCT ON (t.nextgen_id)
    t.nextgen_id,
    t.max_flow,
    t.model_run_time,
    t.max_hour,
    s.flow,
    s.geometry
FROM t_flow_per_nextgen t
JOIN s_flood_inundation_ar s
  ON s.nextgen_id::text = t.nextgen_id
 WHERE s.flow <= t.max_flow
ORDER BY t.nextgen_id, s.flow DESC;

-- ITEM #2
-- select the appropriate flooded road lines
DROP TABLE IF EXISTS s_flood_road_ln;

CREATE TABLE s_flood_road_ln AS
WITH below_trigger_roads AS (
    SELECT 
        ft.road_id, 
        ft.nextgen_id, 
        ft.min_flood_flow, 
        mf.max_flow, 
        mf.model_run_time
    FROM 
        t_road_flood_trigger ft
    INNER JOIN 
        t_flow_per_nextgen mf 
        ON ft.nextgen_id = mf.nextgen_id
    WHERE 
        ft.min_flood_flow < mf.max_flow
),
joined_roads AS (
    SELECT 
        s.geometry,
        s.osm_id,
        s.fclass,
        s.name,
        s.ref,
        s.road_id,
        btr.nextgen_id, 
        btr.min_flood_flow, 
        btr.max_flow, 
        btr.model_run_time
    FROM 
        below_trigger_roads btr
    JOIN 
        s_road_segment_ln s 
        ON btr.road_id = s.road_id
),
deduped_by_attributes AS (
    SELECT DISTINCT ON (
        osm_id, fclass, name, ref, road_id, nextgen_id, 
        min_flood_flow, max_flow, model_run_time
    )
    geometry,
    osm_id,
    fclass,
    name,
    ref,
    road_id,
    nextgen_id, 
    min_flood_flow, 
    max_flow, 
    model_run_time
    FROM joined_roads
    ORDER BY 
        osm_id, fclass, name, ref, road_id, nextgen_id, 
        min_flood_flow, max_flow, model_run_time
),
deduped_by_geometry AS (
    SELECT DISTINCT ON (geometry)
        geometry,
        osm_id,
        fclass,
        name,
        ref,
        road_id,
        nextgen_id, 
        min_flood_flow, 
        max_flow, 
        model_run_time
    FROM deduped_by_attributes
    ORDER BY geometry
)
SELECT * FROM deduped_by_geometry;

-- ITEM #3
-- create a grid of tiles over the s_selected_flood_ar
/*DROP TABLE IF EXISTS s_flood_grid_ar;


CREATE TABLE s_flood_grid_ar AS
WITH ext AS (
    SELECT ST_SetSRID(ST_Extent(geometry)::box2d, 4326) AS geom_extent
    FROM s_flood_merge_ar
),
grid AS (
    SELECT ST_Collect(sg.geom) AS geom_collection
    FROM ext, ST_SquareGrid(0.25, ext.geom_extent) AS sg(geom)
),
dumped AS (
    SELECT (ST_Dump(geom_collection)).geom
    FROM grid
)
SELECT 
    row_number() OVER () AS id,
    dumped.geom
FROM dumped;

ALTER TABLE s_flood_grid_ar ADD PRIMARY KEY (id);

CREATE INDEX idx_s_flood_grid_ar_geom ON s_flood_grid_ar USING GIST (geom);
*/

-- ITEM #3 - revised 2025.06.09
-- Create a grid of tiles over the s_selected_flood_ar
DROP TABLE IF EXISTS s_flood_grid_ar;

CREATE TABLE s_flood_grid_ar AS
WITH ext AS (
    SELECT ST_SetSRID(ST_Extent(geometry)::box2d, 4326) AS geom_extent
    FROM s_selected_flood_ar
),
grid AS (
    SELECT ST_Collect(sg.geom) AS geom_collection
    FROM ext, ST_SquareGrid(0.25, ext.geom_extent) AS sg(geom)
),
dumped AS (
    SELECT (ST_Dump(geom_collection)).geom
    FROM grid
)
SELECT 
    row_number() OVER () AS id,
    dumped.geom
FROM dumped;

ALTER TABLE s_flood_grid_ar ADD PRIMARY KEY (id);
CREATE INDEX idx_s_flood_grid_ar_geom ON s_flood_grid_ar USING GIST (geom);


-- ITEM #4
-- merge flood polygons by tiles
-- heavy calculation
DROP TABLE IF EXISTS s_flood_merge_by_tile_ar;

-- Create merged flood polygons by tile (47 seconds -- 117 tiles (0.25 degree))
CREATE TABLE s_flood_merge_by_tile_ar AS
SELECT
    g.id AS tile_id,
    MIN(sfa.model_run_time) AS model_run_time,
    ST_Multi(ST_Union(sfa.geometry)) AS geometry,
    1::integer AS is_real
FROM 
    s_flood_grid_ar g
JOIN 
    s_selected_flood_ar sfa
ON 
    ST_Intersects(g.geom, sfa.geometry)
GROUP BY 
    g.id;
	
-- ITEM #5
-- Intersect and index s_flood_road_ln by tile_id from s_flood_grid_ar
DROP TABLE IF EXISTS s_flood_road_ln_tile;

CREATE TABLE s_flood_road_ln_tile AS
SELECT
    g.id AS tile_id,
    r.osm_id,
    r.fclass,
    r.name,
    r.ref,
    r.road_id,
    r.nextgen_id,
    r.min_flood_flow,
    r.max_flow,
    r.model_run_time,
    ST_Intersection(r.geometry, g.geom) AS geometry
FROM 
    s_flood_grid_ar g
JOIN 
    s_flood_road_ln r
ON 
    ST_Intersects(r.geometry, g.geom);
	
CREATE INDEX idx_s_flood_road_ln_tile_geom ON s_flood_road_ln_tile USING GIST (geometry);
CREATE INDEX idx_s_flood_road_ln_tile_tile_id ON s_flood_road_ln_tile (tile_id);

-- ITEM #6
-- Create the clipped flooded road lines per tile (~ 8 seconds -- 2581 lines)
DROP TABLE IF EXISTS s_flood_road_trim_ln;

CREATE TABLE s_flood_road_trim_ln AS
SELECT
    r.tile_id,
    r.osm_id,
    r.fclass,
    r.name,
    r.ref,
    r.road_id,
    r.nextgen_id,
    r.min_flood_flow,
    r.max_flow,
    r.model_run_time,
    ST_Intersection(r.geometry, f.geometry) AS geometry,
    ROUND(
        ST_Length(
            ST_Transform(
                ST_Intersection(r.geometry, f.geometry), 3857
            )
        ) * 3.28084
    ) AS length_ft
FROM
    s_flood_road_ln_tile r
JOIN
    s_flood_merge_by_tile_ar f
    ON r.tile_id = f.tile_id
WHERE
    ST_Intersects(r.geometry, f.geometry);

CREATE INDEX idx_s_flood_road_trim_ln_geom ON s_flood_road_trim_ln USING GIST (geometry);
CREATE INDEX idx_s_flood_road_trim_ln_tile_id ON s_flood_road_trim_ln (tile_id);

-- ITEM #7
-- Clip the flood innundation to each tile's limit
DROP TABLE IF EXISTS s_flood_merge_ar;

CREATE TABLE s_flood_merge_ar AS
SELECT 
    f.tile_id,
    ST_Intersection(f.geometry, g.geom) AS geometry
FROM 
    s_flood_merge_by_tile_ar f
JOIN 
    s_flood_grid_ar g ON f.tile_id = g.id
WHERE 
    ST_Intersects(f.geometry, g.geom);
	
-- Assign SRID if missing (only needed if ST_SRID returns 0)
UPDATE s_flood_road_ln SET geometry = ST_SetSRID(geometry, 4326) WHERE ST_SRID(geometry) = 0;
UPDATE s_flood_merge_ar SET geometry = ST_SetSRID(geometry, 4326) WHERE ST_SRID(geometry) = 0;

-- Set tile_id as PRIMARY KEY
ALTER TABLE s_flood_merge_ar
ADD CONSTRAINT s_flood_merge_ar_pkey PRIMARY KEY (tile_id);

ALTER TABLE s_flood_road_ln
ADD CONSTRAINT s_flood_road_ln_pkey PRIMARY KEY (tile_id);

-- Create the new table with a single row containing the first model_run_time value from t_flow_forecast
DROP TABLE IF EXISTS t_current_forecast;

CREATE TABLE t_current_forecast AS
SELECT model_run_time
FROM t_flow_forecast
LIMIT 1;

-- Need to add col to s_flood_merge_ar
ALTER TABLE s_flood_merge_ar
ADD COLUMN model_run_time TEXT;

-- Insert one row if s_flood_merge_ar is empty
INSERT INTO s_flood_merge_ar (model_run_time) SELECT NULL WHERE NOT EXISTS (SELECT 1 FROM s_flood_merge_ar);

UPDATE s_flood_merge_ar
SET model_run_time = (SELECT model_run_time FROM t_current_forecast LIMIT 1);

-- Release the advisory lock manually (optional, as it auto-releases at session end)
SELECT pg_advisory_unlock(20250628);