#!/bin/bash

databases=(
  ABL AMA ATL AUS BMT BRY BWD CHS CRP DAL ELP FTW
  LFK ODA PAR PHR SAT SJT YKM
)

HOST=localhost
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
EOF

  echo "Done with $db"
done
