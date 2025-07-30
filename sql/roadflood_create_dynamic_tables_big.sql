-- SETTING A TIMEOUT FOR HEAVY QUERIES
SET statement_timeout TO '3min';

-- Acquire an advisory lock to prevent concurrent executions
SELECT pg_advisory_lock(20250628);

-- ITEM #0: Establish flows per stream
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
CREATE INDEX idx_t_flow_per_nextgen_feature_id ON t_flow_per_nextgen(feature_id);

-- ITEM #1: select the appropriate flood area polygons
DROP TABLE IF EXISTS s_selected_flood_ar;

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

CREATE INDEX idx_s_selected_flood_ar_geom ON s_selected_flood_ar USING GIST (geometry);

-- ITEM #2: select the appropriate flooded road lines
DROP TABLE IF EXISTS s_flood_road_ln;

CREATE TABLE s_flood_road_ln AS
WITH below_trigger_roads AS (
    SELECT 
        ft.road_id, 
        ft.nextgen_id, 
        ft.min_flood_flow, 
        mf.max_flow, 
        mf.model_run_time
    FROM t_road_flood_trigger ft
    INNER JOIN t_flow_per_nextgen mf ON ft.nextgen_id = mf.nextgen_id
    WHERE ft.min_flood_flow < mf.max_flow
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
    FROM below_trigger_roads btr
    JOIN s_road_segment_ln s ON btr.road_id = s.road_id
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
    ORDER BY osm_id, fclass, name, ref, road_id, nextgen_id, min_flood_flow, max_flow, model_run_time
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


-- ITEM #3: create grid over selected flood areas
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
    SELECT (ST_Dump(geom_collection)).geom FROM grid
)
SELECT 
    row_number() OVER () AS id,
    dumped.geom
FROM dumped;

ALTER TABLE s_flood_grid_ar ADD PRIMARY KEY (id);
CREATE INDEX idx_s_flood_grid_ar_geom ON s_flood_grid_ar USING GIST (geom);

-- ITEM #4: merge flood polygons by tiles
DROP TABLE IF EXISTS s_flood_merge_by_tile_ar;

CREATE TABLE s_flood_merge_by_tile_ar AS
SELECT
    g.id AS tile_id,
    MIN(sfa.model_run_time) AS model_run_time,
    ST_Multi(ST_Union(sfa.geometry)) AS geometry,
    1::integer AS is_real
FROM s_flood_grid_ar g
JOIN s_selected_flood_ar sfa ON ST_Intersects(g.geom, sfa.geometry)
GROUP BY g.id;

CREATE INDEX idx_s_flood_merge_by_tile_ar_tile_id ON s_flood_merge_by_tile_ar(tile_id);
CREATE INDEX idx_s_flood_merge_by_tile_ar_geom ON s_flood_merge_by_tile_ar USING GIST (geometry);

-- ITEM #5: Intersect flooded roads with tiles
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
FROM s_flood_grid_ar g
JOIN s_flood_road_ln r ON ST_Intersects(r.geometry, g.geom);

-- ALTER TABLE s_flood_road_ln_tile ADD PRIMARY KEY (tile_id);

CREATE INDEX idx_s_flood_road_ln_tile_geom ON s_flood_road_ln_tile USING GIST (geometry);
CREATE INDEX idx_s_flood_road_ln_tile_tile_id ON s_flood_road_ln_tile (tile_id);

-- ITEM #6: Create trimmed flooded roads per tile
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
FROM s_flood_road_ln_tile r
JOIN s_flood_merge_by_tile_ar f ON r.tile_id = f.tile_id
WHERE ST_Intersects(r.geometry, f.geometry);

CREATE INDEX idx_s_flood_road_trim_ln_geom ON s_flood_road_trim_ln USING GIST (geometry);
CREATE INDEX idx_s_flood_road_trim_ln_tile_id ON s_flood_road_trim_ln (tile_id);

-- ITEM #7: Clip flood polygons to tiles
DROP TABLE IF EXISTS s_flood_merge_ar;

CREATE TABLE s_flood_merge_ar AS
SELECT 
    f.tile_id,
    ST_Intersection(f.geometry, g.geom) AS geometry
FROM s_flood_merge_by_tile_ar f
JOIN s_flood_grid_ar g ON f.tile_id = g.id
WHERE ST_Intersects(f.geometry, g.geom);

-- Ensure SRID
UPDATE s_flood_merge_ar SET geometry = ST_SetSRID(geometry, 4326) WHERE ST_SRID(geometry) = 0;

ALTER TABLE s_flood_merge_ar ADD PRIMARY KEY (tile_id);
CREATE INDEX idx_s_flood_merge_ar_geom ON s_flood_merge_ar USING GIST (geometry);

-- ITEM #8: Store latest forecast time
DROP TABLE IF EXISTS t_current_forecast;

CREATE TABLE t_current_forecast AS
SELECT model_run_time FROM t_flow_forecast LIMIT 1;

-- Ensure model_run_time column exists
ALTER TABLE s_flood_merge_ar ADD COLUMN IF NOT EXISTS model_run_time TEXT;

-- Update only if there are rows
UPDATE s_flood_merge_ar
SET model_run_time = (SELECT model_run_time FROM t_current_forecast LIMIT 1);

-- Log a warning if the table is empty
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM s_flood_merge_ar) THEN
        RAISE WARNING 's_flood_merge_ar is empty. No flood polygons were created for this run.';
    END IF;
END $$;

-- Release advisory lock
SELECT pg_advisory_unlock(20250628);
