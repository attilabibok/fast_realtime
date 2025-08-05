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

fix_dbs=(
  05_LBB_realtime_hand
  06_ODA_realtime_hand
  15_SAT_realtime_hand
  22_LRD_realtime_hand
)

HOST=postgis
PORT=5432
USER=admin
PGPASSWORD=admin123
export PGPASSWORD

for db in "${databases[@]}"; do
  echo "Applying changes to $db..."

  psql -h "$HOST" -p "$PORT" -U "$USER" -d "$db" -v ON_ERROR_STOP=1 <<'EOF'

-- ===============================
-- TYPE FIX: convert text types to numeric in 5,6,16,22
-- ===============================

DO $$
DECLARE
    col RECORD;
BEGIN
    FOR col IN
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 's_bridge_warning_pnt'
          AND column_name IN (
              'is_overtop', 'max_wse', 'min_dist_to_low_ch',
              'min_ground', 'min_low_ch', 'min_overtop'
          )
    LOOP
        BEGIN
            IF col.column_name = 'is_overtop' AND col.data_type != 'bigint' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN is_overtop TYPE bigint USING is_overtop::bigint';
            ELSIF col.column_name = 'max_wse' AND col.data_type != 'double precision' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN max_wse TYPE double precision USING max_wse::double precision';
            ELSIF col.column_name = 'min_dist_to_low_ch' AND col.data_type != 'double precision' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN min_dist_to_low_ch TYPE double precision USING min_dist_to_low_ch::double precision';
            ELSIF col.column_name = 'min_ground' AND col.data_type != 'double precision' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN min_ground TYPE double precision USING min_ground::double precision';
            ELSIF col.column_name = 'min_low_ch' AND col.data_type != 'double precision' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN min_low_ch TYPE double precision USING min_low_ch::double precision';
            ELSIF col.column_name = 'min_overtop' AND col.data_type != 'double precision' THEN
                EXECUTE 'ALTER TABLE public.s_bridge_warning_pnt ALTER COLUMN min_overtop TYPE double precision USING min_overtop::double precision';
            END IF;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE '⚠️ [%] Could not alter column %: %', current_database(), col.column_name, SQLERRM;
        END;
    END LOOP;
END $$;


-- ===============================
-- Add workflow_id to the tables
-- ===============================
DO $$
DECLARE
  tbl TEXT;
  input_tables TEXT[] := ARRAY[
    't_flow_forecast',
    't_nextgen_to_nwm',
    't_road_flood_trigger',
    's_flood_inundation_ar',
    's_road_segment_ln'
  ];
  output_tables TEXT[] := ARRAY[
    't_flow_per_nextgen',
    's_bridge_warning_pnt',
    's_selected_flood_ar',
    's_flood_road_ln',
    's_flood_grid_ar',
    's_flood_merge_by_tile_ar',
    's_flood_road_ln_tile',
    's_flood_road_trim_ln',
    's_flood_merge_ar',
    't_current_forecast'
  ];
BEGIN
  -- Add workflow_id to input tables
  FOREACH tbl IN ARRAY input_tables LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_name = tbl AND column_name = 'workflow_id' AND table_schema = 'public'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN workflow_id TEXT DEFAULT ''default'';', tbl);
      EXECUTE format('UPDATE public.%I SET workflow_id = ''default'' WHERE workflow_id IS NULL;', tbl);
    END IF;
  END LOOP;

  -- Add workflow_id to output tables
  FOREACH tbl IN ARRAY output_tables LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_name = tbl AND column_name = 'workflow_id' AND table_schema = 'public'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN workflow_id TEXT DEFAULT ''default'';', tbl);
      EXECUTE format('UPDATE public.%I SET workflow_id = ''default'' WHERE workflow_id IS NULL;', tbl);
    END IF;
  END LOOP;

-- ===============================
-- Add primary keys to make a compatible WFS source
-- ===============================
  -- Add primary keys if safe
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 's_flood_merge_ar' AND column_name = 'tile_id'
  )
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 's_flood_merge_ar_pkey'
  ) THEN
    EXECUTE 'ALTER TABLE s_flood_merge_ar ADD CONSTRAINT s_flood_merge_ar_pkey PRIMARY KEY (tile_id)';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 's_flood_road_ln' AND column_name = 'tile_id'
  )
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 's_flood_road_ln_pkey'
  ) THEN
    EXECUTE 'ALTER TABLE s_flood_road_ln ADD CONSTRAINT s_flood_road_ln_pkey PRIMARY KEY (tile_id)';
  END IF;

  -- Create GIST indexes if missing
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

  -- Create B-tree indexes if helpful
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

  -- Create indexes for t_flow_forecast
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_forecast_feature_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_forecast_feature_id ON public.t_flow_forecast (feature_id)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_forecast_model_run_time'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_forecast_model_run_time ON public.t_flow_forecast (model_run_time)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_t_flow_forecast_workflow_id'
  ) THEN
    EXECUTE 'CREATE INDEX idx_t_flow_forecast_workflow_id ON public.t_flow_forecast (workflow_id)';
  END IF;

END $$;

EOF

  echo "Done with $db"
done