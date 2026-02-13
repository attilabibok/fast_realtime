#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be available on postgis:5432..."
until pg_isready -h postgis -p 5432 -U admin; do
  sleep 2
done

echo "PostgreSQL is ready."

BASE_URL="https://knatempstorage.s3.us-west-1.amazonaws.com/tx-fast-pgis-db"
TARGET_DIR="/dumps"
DROP_EXISTING="${DROP_EXISTING:-false}"

mkdir -p "${TARGET_DIR}"

files=(
    "01_PAR_realtime_hand.dump"
    "02_FTW_realtime_hand.dump"
    "03_WFS_realtime_hand.dump"
    "04_AMA_realtime_hand.dump"
    "05_LBB_realtime_hand.dump"
    "06_ODA_realtime_hand.dump"
    "07_SJT_realtime_hand.dump"
    "08_ABL_realtime_hand.dump"
    "09_WAC_realtime_hand.dump"
    "10_TYL_realtime_hand.dump"
    "11_LFK_realtime_hand.dump"
    "12_HOU_realtime_hand.dump"
    "13_YKM_realtime_hand.dump"
    "14_AUS_realtime_hand.dump"
    "15_SAT_realtime_hand.dump"
    "16_CRP_realtime_hand.dump"
    "17_BRY_realtime_hand.dump"
    "18_DAL_realtime_hand.dump"
    "19_ATL_realtime_hand.dump"
    "20_BMT_realtime_hand.dump"
    "21_PHR_realtime_hand.dump"
    "22_LRD_realtime_hand.dump"
    "23_BWD_realtime_hand.dump"
    "24_ELP_realtime_hand.dump"
    "25_CHS_realtime_hand.dump"
)

for file in "${files[@]}"; do
    dump_file="${TARGET_DIR}/${file}"
    db_name=$(basename "$file" .dump)
    tmp_db="${db_name}_tmp"

    echo "Processing $db_name"

    # Drop final DB if DROP_EXISTING is set
    if [ "$DROP_EXISTING" = "true" ]; then
        echo "DROP_EXISTING=true: Dropping $db_name if it exists..."
        dropdb -h postgis -U admin "$db_name" --if-exists
    else
        echo "Checking if $db_name exists..."
        if psql -h postgis -U admin -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1; then
            echo "Database $db_name already exists. Skipping..."
            continue
        fi
    fi

    # Clean up old temp DB if left behind
    dropdb -h postgis -U admin "$tmp_db" --if-exists

    echo "Downloading $file..."
    curl -fSL "${BASE_URL}/${file}" -o "${dump_file}"

    echo "Creating temporary database $tmp_db..."
    createdb -h postgis -U admin "$tmp_db"

    echo "Restoring into $tmp_db..."
    if pg_restore -h postgis -U admin --no-owner --role=admin -d "$tmp_db" "$dump_file"; then
        echo "Restore successful. Renaming $tmp_db to $db_name..."
        dropdb -h postgis -U admin "$db_name" --if-exists
        psql -h postgis -U admin -d postgres -c "ALTER DATABASE \"$tmp_db\" RENAME TO \"$db_name\";"
        echo "Database $db_name is now ready."
    else
        echo "❌ Restore failed for $db_name. Leaving $tmp_db for inspection."
        continue
    fi

    echo "Cleaning up $dump_file..."
    rm -f "$dump_file"
done

echo "✅ All regional databases processed."

# --- TXFull setup ---

if psql -h postgis -U admin -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'TXFull'" | grep -q 1; then
  echo "Database TXFull already exists. Skipping..."
else
  echo "Creating TXFull..."
  createdb -h postgis -U admin TXFull
fi

echo "Altering TXFull tables..."
bash "/postgres_init/alter_existing_dyn_tables.sh"
echo "Altering District tables..."
PGHOST=postgis PGPORT=5432 PGUSER=admin PGPASSWORD="${PGPASSWORD:-admin123}" TXFULL_DB=TXFull \
  bash "/postgres_init/wire_txfull_forecast.sh"
echo "Loading district LWC seed data..."
PGHOST=postgis PGPORT=5432 PGUSER=admin PGPASSWORD="${PGPASSWORD:-admin123}" \
  bash "/postgres_init/load_lwc_data.sh"

echo "Setting up TXFull views..."
psql -h postgis -U admin -d TXFull -f /postgres_init/create_foreign_data_views.sql
psql -h postgis -U admin -d TXFull -f /postgres_init/create_merged_materialized_view.sql

echo "✅ TXFull setup complete."
