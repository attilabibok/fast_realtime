#!/usr/bin/env bash
set -euo pipefail

HOST="${PGHOST:-postgis}"
PORT="${PGPORT:-5432}"
USER="${PGUSER:-admin}"
PGPASSWORD="${PGPASSWORD:-admin123}"
export PGPASSWORD

SEED_CSV="/postgres_init/lwc_seed.csv"

if [[ ! -f "${SEED_CSV}" ]]; then
  echo "[ERROR] LWC seed file not found: ${SEED_CSV}" >&2
  exit 1
fi

# Basic CSV shape check: header + 12 columns per data row.
# This catches malformed comma counts before \copy fails mid-run.
if ! awk -F, 'NR==1 {next} NF!=12 {printf("[ERROR] Malformed CSV row %d has %d columns (expected 12): %s\n", NR, NF, $0); bad=1} END {exit bad}' "${SEED_CSV}"; then
  exit 1
fi

databases=(
  "01 PAR"
  "02 FTW"
  "03 WFS"
  "04 AMA"
  "05 LBB"
  "06 ODA"
  "07 SJT"
  "08 ABL"
  "09 WAC"
  "10 TYL"
  "11 LFK"
  "12 HOU"
  "13 YKM"
  "14 AUS"
  "15 SAT"
  "16 CRP"
  "17 BRY"
  "18 DAL"
  "19 ATL"
  "20 BMT"
  "21 PHR"
  "22 LRD"
  "23 BWD"
  "24 ELP"
  "25 CHS"
)

for entry in "${databases[@]}"; do
  read -r did dcode <<< "${entry}"
  db_name="${did}_${dcode}_realtime_hand"

  echo "[LWC] Preparing ${db_name} (${dcode})"

  psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${db_name}" \
    -v ON_ERROR_STOP=1 \
    -v district_code="${dcode}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS public.s_lwc_static_pnt (
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
  ON public.s_lwc_static_pnt (feature_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_static_pnt_geom
  ON public.s_lwc_static_pnt USING GIST (geometry);

CREATE TABLE IF NOT EXISTS public.s_lwc_pnt (
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
  ON public.s_lwc_pnt (feature_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_pnt_workflow_id
  ON public.s_lwc_pnt (workflow_id);

CREATE INDEX IF NOT EXISTS idx_s_lwc_pnt_geom
  ON public.s_lwc_pnt USING GIST (geometry);

ALTER TABLE public.s_lwc_static_pnt
  ALTER COLUMN q_overtopped DROP NOT NULL;

ALTER TABLE public.s_lwc_pnt
  ALTER COLUMN q_overtopped DROP NOT NULL;

TRUNCATE TABLE public.s_lwc_static_pnt;
DELETE FROM public.s_lwc_pnt;

CREATE TEMP TABLE tmp_lwc_seed (
    district_code TEXT,
    hydro_id BIGINT,
    model_id BIGINT,
    feature_id BIGINT,
    name TEXT,
    osm_id TEXT,
    fclass TEXT,
    q_overtopped BIGINT,
    q_0_5_ft BIGINT,
    q_2_ft BIGINT,
    q_5_ft BIGINT,
    geometry_wkt TEXT
);

\copy tmp_lwc_seed (district_code, hydro_id, model_id, feature_id, name, osm_id, fclass, q_overtopped, q_0_5_ft, q_2_ft, q_5_ft, geometry_wkt) FROM '/postgres_init/lwc_seed.csv' WITH (FORMAT csv, HEADER true)

INSERT INTO public.s_lwc_static_pnt (
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
    geometry
)
SELECT
    hydro_id AS lwc_id,
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
    ST_SetSRID(ST_GeomFromText(geometry_wkt), 4326)
FROM tmp_lwc_seed
WHERE district_code = :'district_code';
SQL

done

echo "[LWC] District LWC static + dynamic tables are ready."
