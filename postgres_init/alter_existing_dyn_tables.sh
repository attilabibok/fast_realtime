#!/bin/bash

databases=(
  01_PAR_realtime_hand
  02_FTW_realtime_hand
  03_WFS_realtime_hand
  04_AMA_realtime_hand
  05_LBB_realtime_hand
  06_ODA_realtime_hand
  07_SJT_realtime_hand
  08_ABL_realtime_hand
  09_WAC_realtime_hand
  10_TYL_realtime_hand
  11_LFK_realtime_hand
  12_HOU_realtime_hand
  13_YKM_realtime_hand
  14_AUS_realtime_hand
  15_SAT_realtime_hand
  16_CRP_realtime_hand
  17_BRY_realtime_hand
  18_DAL_realtime_hand
  19_ATL_realtime_hand
  20_BMT_realtime_hand
  21_PHR_realtime_hand
  22_LRD_realtime_hand
  23_BWD_realtime_hand
  24_ELP_realtime_hand
  25_CHS_realtime_hand
)

HOST=postgis
PORT=5432
USER=admin
PGPASSWORD=admin123
export PGPASSWORD

for db in "${databases[@]}"; do
  echo "Applying changes to $db..."

  psql -h "$HOST" -p "$PORT" -U "$USER" -d "$db" -v ON_ERROR_STOP=1 <<'EOF'
-- Add primary key to s_flood_merge_ar if safe
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 's_flood_merge_ar' AND column_name = 'tile_id'
  )
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 's_flood_merge_ar_pkey'
  ) THEN
    EXECUTE 'ALTER TABLE s_flood_merge_ar ADD CONSTRAINT s_flood_merge_ar_pkey PRIMARY KEY (tile_id)';
  END IF;
END$$;

-- Add primary key to s_flood_road_ln if safe
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 's_flood_road_ln' AND column_name = 'tile_id'
  )
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 's_flood_road_ln_pkey'
  ) THEN
    EXECUTE 'ALTER TABLE s_flood_road_ln ADD CONSTRAINT s_flood_road_ln_pkey PRIMARY KEY (tile_id)';
  END IF;
END$$;

-- Add GIST geometry indexes if missing
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_merge_ar_geom'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_merge_ar_geom ON s_flood_merge_ar USING GIST (geometry)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_grid_ar_geom'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_grid_ar_geom ON s_flood_grid_ar USING GIST (geom)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_road_ln_tile_geom'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_road_ln_tile_geom ON s_flood_road_ln_tile USING GIST (geometry)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_road_trim_ln_geom'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_road_trim_ln_geom ON s_flood_road_trim_ln USING GIST (geometry)';
  END IF;
END$$;

-- Add B-tree indexes for tile_id or other columns where helpful
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_road_ln_tile_tile_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_road_ln_tile_tile_id ON s_flood_road_ln_tile (tile_id)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_s_flood_road_trim_ln_tile_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_s_flood_road_trim_ln_tile_id ON s_flood_road_trim_ln (tile_id)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_per_nextgen_nextgen_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_per_nextgen_nextgen_id ON t_flow_per_nextgen (nextgen_id)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_forecast_feature_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_forecast_feature_id ON t_flow_forecast (feature_id)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_forecast_model_run_time'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_forecast_model_run_time ON t_flow_forecast (model_run_time)';
  END IF;
END$$;
EOF

  echo "Done with $db"
done