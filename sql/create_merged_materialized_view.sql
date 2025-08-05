-- INUNDATION MAP
DROP MATERIALIZED VIEW IF EXISTS mv_flood_merge_tx;

CREATE MATERIALIZED VIEW mv_flood_merge_tx AS
SELECT 1 * 10000 + tile_id AS tile_id_tx, tile_id, 'PAR' AS source_db, geometry, model_run_time, workflow_id FROM foreign_01.s_flood_merge_ar
UNION ALL
SELECT 2 * 10000 + tile_id, tile_id, 'FTW', geometry, model_run_time, workflow_id FROM foreign_02.s_flood_merge_ar
UNION ALL
SELECT 3 * 10000 + tile_id, tile_id, 'WFS', geometry, model_run_time, workflow_id FROM foreign_03.s_flood_merge_ar
UNION ALL
SELECT 4 * 10000 + tile_id, tile_id, 'AMA', geometry, model_run_time, workflow_id FROM foreign_04.s_flood_merge_ar
UNION ALL
SELECT 5 * 10000 + tile_id, tile_id, 'LBB', geometry, model_run_time, workflow_id FROM foreign_05.s_flood_merge_ar
UNION ALL
SELECT 6 * 10000 + tile_id, tile_id, 'ODA', geometry, model_run_time, workflow_id FROM foreign_06.s_flood_merge_ar
UNION ALL
SELECT 7 * 10000 + tile_id, tile_id, 'SJT', geometry, model_run_time, workflow_id FROM foreign_07.s_flood_merge_ar
UNION ALL
SELECT 8 * 10000 + tile_id, tile_id, 'ABL', geometry, model_run_time, workflow_id FROM foreign_08.s_flood_merge_ar
UNION ALL
SELECT 9 * 10000 + tile_id, tile_id, 'WAC', geometry, model_run_time, workflow_id FROM foreign_09.s_flood_merge_ar
UNION ALL
SELECT 10 * 10000 + tile_id, tile_id, 'TYL', geometry, model_run_time, workflow_id FROM foreign_10.s_flood_merge_ar
UNION ALL
SELECT 11 * 10000 + tile_id, tile_id, 'LFK', geometry, model_run_time, workflow_id FROM foreign_11.s_flood_merge_ar
UNION ALL
SELECT 12 * 10000 + tile_id, tile_id, 'HOU', geometry, model_run_time, workflow_id FROM foreign_12.s_flood_merge_ar
UNION ALL
SELECT 13 * 10000 + tile_id, tile_id, 'YKM', geometry, model_run_time, workflow_id FROM foreign_13.s_flood_merge_ar
UNION ALL
SELECT 14 * 10000 + tile_id, tile_id, 'AUS', geometry, model_run_time, workflow_id FROM foreign_14.s_flood_merge_ar
UNION ALL
SELECT 15 * 10000 + tile_id, tile_id, 'SAT', geometry, model_run_time, workflow_id FROM foreign_15.s_flood_merge_ar
UNION ALL
SELECT 16 * 10000 + tile_id, tile_id, 'CRP', geometry, model_run_time, workflow_id FROM foreign_16.s_flood_merge_ar
UNION ALL
SELECT 17 * 10000 + tile_id, tile_id, 'BRY', geometry, model_run_time, workflow_id FROM foreign_17.s_flood_merge_ar
UNION ALL
SELECT 18 * 10000 + tile_id, tile_id, 'DAL', geometry, model_run_time, workflow_id FROM foreign_18.s_flood_merge_ar
UNION ALL
SELECT 19 * 10000 + tile_id, tile_id, 'ATL', geometry, model_run_time, workflow_id FROM foreign_19.s_flood_merge_ar
UNION ALL
SELECT 20 * 10000 + tile_id, tile_id, 'BMT', geometry, model_run_time, workflow_id FROM foreign_20.s_flood_merge_ar
UNION ALL
SELECT 21 * 10000 + tile_id, tile_id, 'PHR', geometry, model_run_time, workflow_id FROM foreign_21.s_flood_merge_ar
UNION ALL
SELECT 22 * 10000 + tile_id, tile_id, 'LRD', geometry, model_run_time, workflow_id FROM foreign_22.s_flood_merge_ar
UNION ALL
SELECT 23 * 10000 + tile_id, tile_id, 'BWD', geometry, model_run_time, workflow_id FROM foreign_23.s_flood_merge_ar
UNION ALL
SELECT 24 * 10000 + tile_id, tile_id, 'ELP', geometry, model_run_time, workflow_id FROM foreign_24.s_flood_merge_ar
UNION ALL
SELECT 25 * 10000 + tile_id, tile_id, 'CHS', geometry, model_run_time, workflow_id FROM foreign_25.s_flood_merge_ar;


-- -- Create unique index on the global ID
CREATE UNIQUE INDEX mv_flood_merge_tx_uidx ON mv_flood_merge_tx (tile_id_tx);
CREATE INDEX mv_flood_merge_tx_wf_uidx ON mv_flood_merge_tx (workflow_id);

-- -- ROADS

-- Drop the materialized view if it exists
DROP MATERIALIZED VIEW IF EXISTS mv_flood_road_trim_ln_tx;

-- Create the materialized view with road_id_tx as combined key
CREATE MATERIALIZED VIEW mv_flood_road_trim_ln_tx AS
WITH all_roads AS (
    SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id
    FROM foreign_01.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_02.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_03.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_04.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_05.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_06.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_07.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_08.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_09.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_10.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_11.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_12.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_13.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_14.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_15.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_16.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_17.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_18.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_19.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_20.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_21.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_22.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_23.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_24.s_flood_road_trim_ln
    UNION ALL SELECT nextgen_id, osm_id, road_id, tile_id, max_flow, geometry, name, ref, fclass, model_run_time, length_ft, workflow_id FROM foreign_25.s_flood_road_trim_ln
)
SELECT
    (road_id::text || '_' || tile_id::text) AS road_id_tx,
    MIN(nextgen_id) AS nextgen_id,
    MIN(osm_id) AS osm_id,
    road_id,
    tile_id,
    MAX(max_flow) AS max_flow,
    ST_Union(geometry) AS geometry,
    MIN(name) AS name,
    MIN(ref) AS ref,
    MIN(fclass) AS fclass,
    MIN(model_run_time) AS model_run_time,
    SUM(length_ft) AS length_ft,
    workflow_id
FROM all_roads
GROUP BY road_id, tile_id, workflow_id;

-- Create a unique index on the composite text key
CREATE UNIQUE INDEX mv_flood_road_trim_ln_tx_uidx ON mv_flood_road_trim_ln_tx (road_id_tx);
CREATE INDEX mv_flood_road_trim_ln_tx_tile_idx ON mv_flood_road_trim_ln_tx (tile_id);
CREATE INDEX mv_flood_road_trim_ln_tx_wf_idx ON mv_flood_road_trim_ln_tx (workflow_id);




-- Drop the materialized view if it exists
DROP MATERIALIZED VIEW IF EXISTS mv_bridge_warning_pnt_tx;

-- Create the materialized view
CREATE MATERIALIZED VIEW mv_bridge_warning_pnt_tx AS

SELECT 1 * 10000 + row_number() OVER () AS bridge_idx_tx,
       geometry,
       "BRDG_ID",
       name,
       ref,
       nhd_name,
       is_overtop,
       min_dist_to_low_ch,
       model_run_time,
       url,
       workflow_id,
       'PAR' AS source_db
FROM foreign_01.s_bridge_warning_pnt

UNION ALL
SELECT 2 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'FTW'
FROM foreign_02.s_bridge_warning_pnt

UNION ALL
SELECT 3 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'WFS'
FROM foreign_03.s_bridge_warning_pnt

UNION ALL
SELECT 4 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'AMA'
FROM foreign_04.s_bridge_warning_pnt

UNION ALL
SELECT 5 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop::bigint, min_dist_to_low_ch::double precision, model_run_time, url, workflow_id, 'LBB'
FROM foreign_05.s_bridge_warning_pnt

UNION ALL
SELECT 6 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop::bigint, min_dist_to_low_ch::double precision, model_run_time, url, workflow_id, 'ODA'
FROM foreign_06.s_bridge_warning_pnt

UNION ALL
SELECT 7 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'SJT'
FROM foreign_07.s_bridge_warning_pnt

UNION ALL
SELECT 8 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'ABL'
FROM foreign_08.s_bridge_warning_pnt

UNION ALL
SELECT 9 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'WAC'
FROM foreign_09.s_bridge_warning_pnt

UNION ALL
SELECT 10 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'TYL'
FROM foreign_10.s_bridge_warning_pnt

UNION ALL
SELECT 11 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'LFK'
FROM foreign_11.s_bridge_warning_pnt

UNION ALL
SELECT 12 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'HOU'
FROM foreign_12.s_bridge_warning_pnt

UNION ALL
SELECT 13 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'YKM'
FROM foreign_13.s_bridge_warning_pnt

UNION ALL
SELECT 14 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'AUS'
FROM foreign_14.s_bridge_warning_pnt

UNION ALL
SELECT 15 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'SAT'
FROM foreign_15.s_bridge_warning_pnt

UNION ALL
SELECT 16 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'CRP'
FROM foreign_16.s_bridge_warning_pnt

UNION ALL
SELECT 17 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'BRY'
FROM foreign_17.s_bridge_warning_pnt

UNION ALL
SELECT 18 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'DAL'
FROM foreign_18.s_bridge_warning_pnt

UNION ALL
SELECT 19 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'ATL'
FROM foreign_19.s_bridge_warning_pnt

UNION ALL
SELECT 20 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'BMT'
FROM foreign_20.s_bridge_warning_pnt

UNION ALL
SELECT 21 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'PHR'
FROM foreign_21.s_bridge_warning_pnt

UNION ALL
SELECT 22 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop::bigint,  min_dist_to_low_ch::double precision, model_run_time, url, workflow_id, 'LRD'
FROM foreign_22.s_bridge_warning_pnt

UNION ALL
SELECT 23 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'BWD'
FROM foreign_23.s_bridge_warning_pnt

UNION ALL
SELECT 24 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'ELP'
FROM foreign_24.s_bridge_warning_pnt

UNION ALL
SELECT 25 * 10000 + row_number() OVER (), geometry, "BRDG_ID", name, ref, nhd_name, is_overtop, min_dist_to_low_ch, model_run_time, url, workflow_id, 'CHS'
FROM foreign_25.s_bridge_warning_pnt;

-- Create a unique index on the global bridge index
CREATE UNIQUE INDEX mv_bridge_warning_pnt_tx_uidx ON mv_bridge_warning_pnt_tx (bridge_idx_tx);
CREATE INDEX mv_bridge_warning_pnt_wf_uidx ON mv_bridge_warning_pnt_tx (workflow_id);
