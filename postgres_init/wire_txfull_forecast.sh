#!/usr/bin/env bash
set -euo pipefail

# =========================
# CONFIG — EDIT IF NEEDED
# =========================
export PGHOST="${PGHOST:-postgis}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-admin}"
export PGPASSWORD="${PGPASSWORD:-admin123}"

TXFULL_DB="${TXFULL_DB:-TXFull}"

# Hardcoded fallback list (used if auto-discovery finds nothing)
FALLBACK_DISTRICTS=(
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

FDW_SERVER_NAME="txfull_fdw"
FDW_SCHEMA="txfull"
FDW_REMOTE_SCHEMA="public"

# Remote table names in TXFull
TBL_FORECAST="t_flow_forecast"
TBL_CURRENT="t_current_forecast"

say() { echo "[$(date +'%F %T')] $*"; }
psql_db() { local db="$1"; shift; psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$db" -v ON_ERROR_STOP=1 -q -c "$*"; }
psql_here() { local db="$1"; shift; psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$db" -v ON_ERROR_STOP=1 -q "$@"; }

say "Checking PostgreSQL connectivity at ${PGHOST}:${PGPORT} as ${PGUSER}..."
if ! psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=postgres" -tA -q -c "SELECT 1;" >/dev/null 2>&1; then
  say "ERROR: Cannot connect to PostgreSQL at ${PGHOST}:${PGPORT}. Set PGHOST/PGPORT/PGUSER/PGPASSWORD correctly."
  exit 1
fi

# =========================
# 0) Discover district DBs
# =========================
say "Discovering district databases…"
mapfile -t DISTRICTS < <(
  psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=postgres" -tA -q \
    -c "SELECT datname
        FROM pg_database
        WHERE datname ~ '^[0-9]{2}_[A-Z]{3}_realtime_hand$'
        ORDER BY datname;"
)
if (( ${#DISTRICTS[@]} == 0 )); then
  say "Auto-discovery found none; using fallback list."
  DISTRICTS=("${FALLBACK_DISTRICTS[@]}")
fi
say "District DBs: ${DISTRICTS[*]}"

# =========================
# 1) Ensure TXFull tables exist (+ indexes)
# =========================
say "Ensuring ${TXFULL_DB}.public.${TBL_FORECAST} exists & is up-to-date…"
psql_here "$TXFULL_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS public.t_flow_forecast (
    feature_id      BIGINT,
    model_run_time  TEXT,
    flow_t00        BIGINT,
    flow_t01        BIGINT,
    flow_t02        BIGINT,
    flow_t03        BIGINT,
    flow_t04        BIGINT,
    flow_t05        BIGINT,
    flow_t06        BIGINT,
    flow_t07        BIGINT,
    flow_t08        BIGINT,
    flow_t09        BIGINT,
    flow_t10        BIGINT,
    flow_t11        BIGINT,
    flow_t12        BIGINT,
    flow_t13        BIGINT,
    flow_t14        BIGINT,
    flow_t15        BIGINT,
    flow_t16        BIGINT,
    flow_t17        BIGINT,
    workflow_id     TEXT
);
ALTER TABLE public.t_flow_forecast
    ADD COLUMN IF NOT EXISTS feature_id     BIGINT,
    ADD COLUMN IF NOT EXISTS model_run_time TEXT,
    ADD COLUMN IF NOT EXISTS flow_t00       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t01       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t02       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t03       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t04       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t05       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t06       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t07       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t08       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t09       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t10       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t11       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t12       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t13       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t14       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t15       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t16       BIGINT,
    ADD COLUMN IF NOT EXISTS flow_t17       BIGINT,
    ADD COLUMN IF NOT EXISTS workflow_id    TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE c.relkind='i' AND c.relname='idx_t_flow_forecast_feat' AND n.nspname='public'
    ) THEN
      EXECUTE 'CREATE INDEX idx_t_flow_forecast_feat ON public.t_flow_forecast (feature_id)';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE c.relkind='i' AND c.relname='idx_t_flow_forecast_mrt' AND n.nspname='public'
    ) THEN
      EXECUTE 'CREATE INDEX idx_t_flow_forecast_mrt ON public.t_flow_forecast (model_run_time)';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE c.relkind='i' AND c.relname='idx_t_flow_forecast_wf' AND n.nspname='public'
    ) THEN
      EXECUTE 'CREATE INDEX idx_t_flow_forecast_wf ON public.t_flow_forecast (workflow_id)';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE c.relkind='i' AND c.relname='idx_t_flow_forecast_feat_mrt_wf' AND n.nspname='public'
    ) THEN
      EXECUTE 'CREATE INDEX idx_t_flow_forecast_feat_mrt_wf
               ON public.t_flow_forecast (feature_id, model_run_time, workflow_id)';
    END IF;
END $$;
SQL
say "TXFull ${TBL_FORECAST} ensured."

say "Ensuring ${TXFULL_DB}.public.${TBL_CURRENT} exists & is up-to-date…"
psql_here "$TXFULL_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS public.t_current_forecast (
    model_run_time  TEXT,
    workflow_id     TEXT
);
ALTER TABLE public.t_current_forecast
    ADD COLUMN IF NOT EXISTS model_run_time TEXT,
    ADD COLUMN IF NOT EXISTS workflow_id    TEXT;

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_t_current_forecast_wf
  ON public.t_current_forecast (workflow_id);
CREATE INDEX IF NOT EXISTS idx_t_current_forecast_mrt
  ON public.t_current_forecast (model_run_time);
SQL
say "TXFull ${TBL_CURRENT} ensured."

# =========================
# Helper: ensure FDW server + mapping
# =========================
ensure_fdw_bits() {
  local DB="$1"
  # Extension & schema
  psql_db "$DB" "CREATE EXTENSION IF NOT EXISTS postgres_fdw;"
  psql_db "$DB" "CREATE SCHEMA IF NOT EXISTS ${FDW_SCHEMA};"

  # Server
  psql_db "$DB" "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_foreign_server WHERE srvname='${FDW_SERVER_NAME}') THEN
    EXECUTE 'CREATE SERVER ${FDW_SERVER_NAME}
             FOREIGN DATA WRAPPER postgres_fdw
             OPTIONS (host ''${PGHOST}'', dbname ''${TXFULL_DB}'', port ''${PGPORT}'')';
  END IF;
END \$\$;
ALTER SERVER ${FDW_SERVER_NAME} OPTIONS (
  SET host '${PGHOST}',
  SET dbname '${TXFULL_DB}',
  SET port '${PGPORT}'
);
"

  # User mapping for CURRENT_USER (password if provided)
  if [[ -n "${PGPASSWORD:-}" ]]; then
    psql_db "$DB" "
DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_user_mappings WHERE srvname='${FDW_SERVER_NAME}'
      AND umuser = (SELECT usesysid FROM pg_user WHERE usename=current_user)
  ) THEN
    EXECUTE 'CREATE USER MAPPING FOR CURRENT_USER SERVER ${FDW_SERVER_NAME}
             OPTIONS (user ''${PGUSER}'', password ''${PGPASSWORD}'')';
  ELSE
    EXECUTE 'ALTER USER MAPPING FOR CURRENT_USER SERVER ${FDW_SERVER_NAME}
             OPTIONS (SET user ''${PGUSER}'', SET password ''${PGPASSWORD}'')';
  END IF;
END \$\$;
"
  else
    psql_db "$DB" "
DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_user_mappings WHERE srvname='${FDW_SERVER_NAME}'
      AND umuser = (SELECT usesysid FROM pg_user WHERE usename=current_user)
  ) THEN
    EXECUTE 'CREATE USER MAPPING FOR CURRENT_USER SERVER ${FDW_SERVER_NAME} OPTIONS (user '''||current_user||''')';
  END IF;
END \$\$;
"
  fi
}

# =========================
# Helper: ensure/repair a foreign table
# =========================
ensure_foreign_table() {
  local DB="$1"
  local REMOTE_TABLE="$2"   # e.g., t_flow_forecast or t_current_forecast

  # Expected column list per table
  if [[ "$REMOTE_TABLE" == "t_flow_forecast" ]]; then
    local EXPECTED_COLS="('feature_id'),('model_run_time'),
      ('flow_t00'),('flow_t01'),('flow_t02'),('flow_t03'),
      ('flow_t04'),('flow_t05'),('flow_t06'),('flow_t07'),
      ('flow_t08'),('flow_t09'),('flow_t10'),('flow_t11'),
      ('flow_t12'),('flow_t13'),('flow_t14'),('flow_t15'),
      ('flow_t16'),('flow_t17'),('workflow_id')"
  else
    # t_current_forecast
    local EXPECTED_COLS="('model_run_time'),('workflow_id')"
  fi

  psql_db "$DB" "
DO \$\$
DECLARE
  exists_ft boolean;
  diff_count int := 0;
BEGIN
  SELECT EXISTS(
    SELECT 1 FROM information_schema.tables
    WHERE table_schema='${FDW_SCHEMA}' AND table_name='${REMOTE_TABLE}'
  ) INTO exists_ft;

  IF exists_ft THEN
    WITH expected(name) AS (
      VALUES ${EXPECTED_COLS}
    ),
    existing(name) AS (
      SELECT column_name
      FROM information_schema.columns
      WHERE table_schema='${FDW_SCHEMA}' AND table_name='${REMOTE_TABLE}'
    ),
    diff AS (
      (SELECT name FROM expected EXCEPT SELECT name FROM existing)
      UNION
      (SELECT name FROM existing EXCEPT SELECT name FROM expected)
    )
    SELECT COUNT(*) FROM diff INTO diff_count;

    IF diff_count > 0 THEN
      EXECUTE 'DROP FOREIGN TABLE IF EXISTS ${FDW_SCHEMA}.' || quote_ident('${REMOTE_TABLE}');
      EXECUTE '
        IMPORT FOREIGN SCHEMA ${FDW_REMOTE_SCHEMA}
        LIMIT TO (${REMOTE_TABLE})
        FROM SERVER ${FDW_SERVER_NAME}
        INTO ${FDW_SCHEMA}';
    END IF;
  ELSE
    EXECUTE '
      IMPORT FOREIGN SCHEMA ${FDW_REMOTE_SCHEMA}
      LIMIT TO (${REMOTE_TABLE})
      FROM SERVER ${FDW_SERVER_NAME}
      INTO ${FDW_SCHEMA}';
  END IF;
END \$\$;
"
}

# =========================
# 2) FDW wiring per district (both tables)
# =========================
for DB in "${DISTRICTS[@]}"; do
  say "Configuring FDW in district DB: ${DB}"
  ensure_fdw_bits "$DB"
  ensure_foreign_table "$DB" "$TBL_FORECAST"
  ensure_foreign_table "$DB" "$TBL_CURRENT"
  say "FDW ready in ${DB}: ${FDW_SCHEMA}.${TBL_FORECAST} & ${FDW_SCHEMA}.${TBL_CURRENT}"
done

say "All done."
