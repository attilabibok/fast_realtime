BEGIN;
-- SETTING A TIMEOUT FOR HEAVY QUERIES ( on the first run, it can be very slow)
SET statement_timeout TO '40min';

-- Serialize only per-workflow:
-- Don’t wait around for the per-workflow lock; fail fast if busy.
SET LOCAL lock_timeout = '2s';

-- Try to take a transaction-scoped advisory lock per workflow.
-- If another run with the same workflow_id is active, we abort immediately.
DO $$
BEGIN
  IF NOT pg_try_advisory_xact_lock(hashtext(:'workflow_id'), 0) THEN
    RAISE EXCEPTION 'Workflow % is already running elsewhere. Skipping.', :'workflow_id';
  END IF;
END
$$;


-- Declare the workflow ID
-- \set workflow_id 'default'  -- Override using psql -v workflow_id='your-id'

-- ITEM #0: Establish flows per stream
DELETE FROM t_flow_per_nextgen WHERE workflow_id = :'workflow_id';

INSERT INTO t_flow_per_nextgen (
    nextgen_id, feature_id, model_run_time, flow_array, max_flow, max_hour, workflow_id
)
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
        f.workflow_id,
        ARRAY[f.flow_t00] AS flow_array
    FROM crosswalked c
    JOIN txfull.t_flow_forecast f 
      ON c.feature_id = f.feature_id
    WHERE f.workflow_id = :'workflow_id'
)
SELECT
    nextgen_id,
    feature_id,
    model_run_time,
    flow_array,
    flow_array[1] AS max_flow,
    0 AS max_hour,
    workflow_id
FROM flows_with_array;

-- ITEM #1: select the appropriate flood area polygons
DELETE FROM s_selected_flood_ar WHERE workflow_id = :'workflow_id';

INSERT INTO s_selected_flood_ar (
    nextgen_id, max_flow, model_run_time, max_hour, flow, geometry, workflow_id
)
SELECT DISTINCT ON (t.nextgen_id)
    t.nextgen_id,
    t.max_flow,
    t.model_run_time,
    t.max_hour,
    s.flow,
    s.geometry,
    t.workflow_id
FROM t_flow_per_nextgen t
JOIN s_flood_inundation_ar s
  ON s.nextgen_id::text = t.nextgen_id
WHERE t.workflow_id = :'workflow_id'
  AND s.flow <= t.max_flow
ORDER BY t.nextgen_id, s.flow DESC;


-- ITEM #2: select the appropriate flooded road lines
DELETE FROM s_flood_road_ln WHERE workflow_id = :'workflow_id';

INSERT INTO s_flood_road_ln (
    geometry, osm_id, fclass, name, ref, road_id, nextgen_id, 
    min_flood_flow, max_flow, model_run_time, workflow_id
)
WITH below_trigger_roads AS (
    SELECT 
        ft.road_id, 
        ft.nextgen_id, 
        ft.min_flood_flow, 
        mf.max_flow, 
        mf.model_run_time,
        mf.workflow_id
    FROM t_road_flood_trigger ft
    INNER JOIN t_flow_per_nextgen mf 
        ON ft.nextgen_id = mf.nextgen_id
    WHERE ft.min_flood_flow < mf.max_flow
      AND mf.workflow_id = :'workflow_id'
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
        btr.model_run_time,
        btr.workflow_id
    FROM below_trigger_roads btr
    JOIN s_road_segment_ln s ON btr.road_id = s.road_id
),
deduped AS (
    SELECT DISTINCT ON (
        osm_id, fclass, name, ref, road_id, nextgen_id, 
        min_flood_flow, max_flow, model_run_time
    ) *
    FROM joined_roads
    ORDER BY osm_id, fclass, name, ref, road_id, nextgen_id, min_flood_flow, max_flow, model_run_time
)
SELECT * FROM deduped;

-- ITEM #3: Create grid over selected flood areas
DELETE FROM s_flood_grid_ar WHERE workflow_id = :'workflow_id';

WITH ext AS (
    SELECT ST_SetSRID(ST_Extent(geometry)::box2d, 4326) AS geom_extent
    FROM s_selected_flood_ar
    WHERE workflow_id = :'workflow_id'
),
grid AS (
    SELECT ST_Collect(sg.geom) AS geom_collection
    FROM ext, ST_SquareGrid(0.25, ext.geom_extent) AS sg(geom)
),
dumped AS (
    SELECT (ST_Dump(geom_collection)).geom FROM grid
)
INSERT INTO s_flood_grid_ar (id, geom, workflow_id)
SELECT row_number() OVER (), dumped.geom, :'workflow_id'
FROM dumped;

-- ITEM #4: merge flood polygons by tiles
DELETE FROM s_flood_merge_by_tile_ar WHERE workflow_id = :'workflow_id';

INSERT INTO s_flood_merge_by_tile_ar (tile_id, model_run_time, geometry, is_real, workflow_id)
SELECT
    g.id AS tile_id,
    MIN(sfa.model_run_time) AS model_run_time,
    ST_Multi(ST_Union(sfa.geometry)) AS geometry,
    1::integer AS is_real,
    :'workflow_id'
FROM s_flood_grid_ar g
JOIN s_selected_flood_ar sfa 
  ON ST_Intersects(g.geom, sfa.geometry)
WHERE g.workflow_id = :'workflow_id' AND sfa.workflow_id = :'workflow_id'
GROUP BY g.id;

-- ITEM #5: Intersect flooded roads with tiles
DELETE FROM s_flood_road_ln_tile WHERE workflow_id = :'workflow_id';

INSERT INTO s_flood_road_ln_tile (
    tile_id, osm_id, fclass, name, ref, road_id, nextgen_id, 
    min_flood_flow, max_flow, model_run_time, geometry, workflow_id
)
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
    ST_Intersection(r.geometry, g.geom) AS geometry,
    :'workflow_id'
FROM s_flood_grid_ar g
JOIN s_flood_road_ln r 
  ON ST_Intersects(r.geometry, g.geom)
WHERE g.workflow_id = :'workflow_id' AND r.workflow_id = :'workflow_id';

-- ITEM #6: Create trimmed flooded roads per tile
DELETE FROM s_flood_road_trim_ln WHERE workflow_id = :'workflow_id';

INSERT INTO s_flood_road_trim_ln (
    tile_id, osm_id, fclass, name, ref, road_id, nextgen_id,
    min_flood_flow, max_flow, model_run_time, geometry, length_ft, workflow_id
)
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
    ROUND(ST_Length(ST_Transform(ST_Intersection(r.geometry, f.geometry), 3857)) * 3.28084) AS length_ft,
    :'workflow_id'
FROM s_flood_road_ln_tile r
JOIN s_flood_merge_by_tile_ar f 
  ON r.tile_id = f.tile_id
WHERE r.workflow_id = :'workflow_id' AND f.workflow_id = :'workflow_id'
  AND ST_Intersects(r.geometry, f.geometry);

-- ITEM #7: Clip flood polygons to tiles
DELETE FROM s_flood_merge_ar WHERE workflow_id = :'workflow_id';

INSERT INTO s_flood_merge_ar (
    tile_id, geometry, model_run_time, workflow_id
)
SELECT 
    f.tile_id,
    ST_Intersection(f.geometry, g.geom) AS geometry,
    f.model_run_time,
    :'workflow_id'
FROM s_flood_merge_by_tile_ar f
JOIN s_flood_grid_ar g 
  ON f.tile_id = g.id
WHERE f.workflow_id = :'workflow_id' AND g.workflow_id = :'workflow_id'
  AND ST_Intersects(f.geometry, g.geom);

-- Ensure SRID
UPDATE s_flood_merge_ar 
SET geometry = ST_SetSRID(geometry, 4326) 
WHERE ST_SRID(geometry) = 0 AND workflow_id = :'workflow_id';

-- ITEM #8: Build LWC status points
CREATE TABLE IF NOT EXISTS s_lwc_static_pnt (
    lwc_id BIGINT PRIMARY KEY,
    hydro_id BIGINT,
    model_id BIGINT,
    feature_id BIGINT NOT NULL,
    name TEXT,
    osm_id TEXT,
    fclass TEXT,
    q_overtopped BIGINT,
    q_0_5_ft BIGINT,
    q_2_ft BIGINT,
    q_5_ft BIGINT,
    geometry geometry(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_s_lwc_static_pnt_feature_id
  ON s_lwc_static_pnt (feature_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_static_pnt_geom
  ON s_lwc_static_pnt USING GIST (geometry);

CREATE TABLE IF NOT EXISTS s_lwc_pnt (
    lwc_id BIGINT NOT NULL,
    hydro_id BIGINT,
    model_id BIGINT,
    feature_id BIGINT NOT NULL,
    name TEXT,
    osm_id TEXT,
    fclass TEXT,
    q_overtopped BIGINT,
    q_0_5_ft BIGINT,
    q_2_ft BIGINT,
    q_5_ft BIGINT,
    max_flow BIGINT,
    is_overtopped BIGINT,
    model_run_time TEXT,
    workflow_id TEXT DEFAULT 'default',
    geometry geometry(Point, 4326) NOT NULL,
    PRIMARY KEY (lwc_id, workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_s_lwc_pnt_feature_id
  ON s_lwc_pnt (feature_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_pnt_workflow_id
  ON s_lwc_pnt (workflow_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_pnt_geom
  ON s_lwc_pnt USING GIST (geometry);

ALTER TABLE s_lwc_static_pnt
  ALTER COLUMN q_overtopped DROP NOT NULL;

ALTER TABLE s_lwc_pnt
  ALTER COLUMN q_overtopped DROP NOT NULL;

DELETE FROM s_lwc_pnt WHERE workflow_id = :'workflow_id';

INSERT INTO s_lwc_pnt (
    lwc_id,
    hydro_id,
    model_id,
    feature_id,
    name,
    osm_id,
    fclass,
    q_overtopped,
    q_0_5_ft,
    q_2_ft,
    q_5_ft,
    max_flow,
    is_overtopped,
    model_run_time,
    workflow_id,
    geometry
)
WITH flow_by_feature AS (
    SELECT
        feature_id,
        MAX(max_flow)::bigint AS max_flow,
        MIN(model_run_time) AS model_run_time
    FROM t_flow_per_nextgen
    WHERE workflow_id = :'workflow_id'
    GROUP BY feature_id
),
run_time AS (
    SELECT MAX(model_run_time) AS model_run_time
    FROM txfull.t_flow_forecast
    WHERE workflow_id = :'workflow_id'
)
SELECT
    s.lwc_id,
    s.hydro_id,
    s.model_id,
    s.feature_id,
    s.name,
    s.osm_id,
    s.fclass,
    s.q_overtopped,
    s.q_0_5_ft,
    s.q_2_ft,
    s.q_5_ft,
    COALESCE(f.max_flow, 0) AS max_flow,
    CASE
        WHEN s.q_overtopped IS NULL THEN NULL
        WHEN COALESCE(f.max_flow, 0) >= s.q_overtopped THEN 1
        ELSE 0
    END AS is_overtopped,
    COALESCE(f.model_run_time, rt.model_run_time) AS model_run_time,
    :'workflow_id',
    s.geometry
FROM s_lwc_static_pnt s
LEFT JOIN flow_by_feature f
  ON s.feature_id = f.feature_id
CROSS JOIN run_time rt;

-- ITEM #9: Store latest forecast time
DELETE FROM t_current_forecast WHERE workflow_id = :'workflow_id';

INSERT INTO t_current_forecast (model_run_time, workflow_id)
SELECT model_run_time, :'workflow_id'
FROM txfull.t_flow_forecast
WHERE workflow_id = :'workflow_id'
LIMIT 1;


-- Log a warning if the final table is empty
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM s_flood_merge_ar WHERE workflow_id = :'workflow_id') THEN
        RAISE WARNING 's_flood_merge_ar is empty for workflow_id=%', :'workflow_id';
    END IF;
END $$;

-- Release advisory lock
-- SELECT pg_advisory_unlock(20250628);
COMMIT;
