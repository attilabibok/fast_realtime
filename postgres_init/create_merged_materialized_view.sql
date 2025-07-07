-- Roughly takes 1.5 sec
DROP MATERIALIZED VIEW IF EXISTS mv_flood_merge_tx;

CREATE MATERIALIZED VIEW mv_flood_merge_tx AS
SELECT 1 * 10000 + tile_id AS tile_id_tx, tile_id, 'PAR' AS source_db, geometry, model_run_time FROM foreign_01.s_flood_merge_ar
UNION ALL
SELECT 2 * 10000 + tile_id, tile_id, 'FTW', geometry, model_run_time FROM foreign_02.s_flood_merge_ar
-- UNION ALL
-- SELECT 3 * 10000 + tile_id, tile_id, 'WFS', geometry, model_run_time FROM foreign_03.s_flood_merge_ar
UNION ALL
SELECT 4 * 10000 + tile_id, tile_id, 'AMA', geometry, model_run_time FROM foreign_04.s_flood_merge_ar
-- UNION ALL
-- SELECT 5 * 10000 + tile_id, tile_id, 'LBB', geometry, model_run_time FROM foreign_05.s_flood_merge_ar
UNION ALL
SELECT 6 * 10000 + tile_id, tile_id, 'ODA', geometry, model_run_time FROM foreign_06.s_flood_merge_ar
UNION ALL
SELECT 7 * 10000 + tile_id, tile_id, 'SJT', geometry, model_run_time FROM foreign_07.s_flood_merge_ar
UNION ALL
SELECT 8 * 10000 + tile_id, tile_id, 'ABL', geometry, model_run_time FROM foreign_08.s_flood_merge_ar
-- UNION ALL
-- SELECT 9 * 10000 + tile_id, tile_id, 'WAC', geometry, model_run_time FROM foreign_09.s_flood_merge_ar
-- UNION ALL
-- SELECT 10 * 10000 + tile_id, tile_id, 'TYL', geometry, model_run_time FROM foreign_10.s_flood_merge_ar
UNION ALL
SELECT 11 * 10000 + tile_id, tile_id, 'LFK', geometry, model_run_time FROM foreign_11.s_flood_merge_ar
-- UNION ALL
-- SELECT 12 * 10000 + tile_id, tile_id, 'HOU', geometry, model_run_time FROM foreign_12.s_flood_merge_ar
UNION ALL
SELECT 13 * 10000 + tile_id, tile_id, 'YKM', geometry, model_run_time FROM foreign_13.s_flood_merge_ar
UNION ALL
SELECT 14 * 10000 + tile_id, tile_id, 'AUS', geometry, model_run_time FROM foreign_14.s_flood_merge_ar
UNION ALL
SELECT 15 * 10000 + tile_id, tile_id, 'SAT', geometry, model_run_time FROM foreign_15.s_flood_merge_ar
UNION ALL
SELECT 16 * 10000 + tile_id, tile_id, 'CRP', geometry, model_run_time FROM foreign_16.s_flood_merge_ar
UNION ALL
SELECT 17 * 10000 + tile_id, tile_id, 'BRY', geometry, model_run_time FROM foreign_17.s_flood_merge_ar
UNION ALL
SELECT 18 * 10000 + tile_id, tile_id, 'DAL', geometry, model_run_time FROM foreign_18.s_flood_merge_ar
UNION ALL
SELECT 19 * 10000 + tile_id, tile_id, 'ATL', geometry, model_run_time FROM foreign_19.s_flood_merge_ar
UNION ALL
SELECT 20 * 10000 + tile_id, tile_id, 'BMT', geometry, model_run_time FROM foreign_20.s_flood_merge_ar
UNION ALL
SELECT 21 * 10000 + tile_id, tile_id, 'PHR', geometry, model_run_time FROM foreign_21.s_flood_merge_ar
-- UNION ALL
-- SELECT 22 * 10000 + tile_id, tile_id, 'LRD', geometry, model_run_time FROM foreign_22.s_flood_merge_ar
UNION ALL
SELECT 23 * 10000 + tile_id, tile_id, 'BWD', geometry, model_run_time FROM foreign_23.s_flood_merge_ar
UNION ALL
SELECT 24 * 10000 + tile_id, tile_id, 'ELP', geometry, model_run_time FROM foreign_24.s_flood_merge_ar
UNION ALL
SELECT 25 * 10000 + tile_id, tile_id, 'CHS', geometry, model_run_time FROM foreign_25.s_flood_merge_ar;


-- Create unique index on the global ID
CREATE UNIQUE INDEX mv_flood_merge_tx_uidx ON mv_flood_merge_tx (tile_id_tx);

