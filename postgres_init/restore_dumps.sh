#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be available on postgis:5432..."
until pg_isready -h postgis -p 5432 -U admin; do
  sleep 2
done

echo "PostgreSQL is ready. "

# Check if DOWNLOAD_DUMPS is true
if [ "${DOWNLOAD_DUMPS}" = "true" ]; then
    echo "Calling download_dumps.sh..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    "${SCRIPT_DIR}/download_dumps.sh"
else
    echo "DOWNLOAD_DUMPS is not set to 'true'. Skipping dump download."
fi

echo "Checking and restoring dumps..."
echo "Dump folder content:"
ls -lh /dumps

for dump_file in /dumps/*.dump; do
  [ -e "$dump_file" ] || continue

  db_name=$(basename "$dump_file" _realtime_hand.dump | cut -d_ -f2)
  echo "Dump file: $dump_file"
  echo "Target database: $db_name"

  echo "Checking if database $db_name exists..."
  if psql -h postgis -U admin -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1; then
    echo "Database $db_name exists. Skipping..."
  else
    echo "Creating and restoring $db_name..."
    createdb -h postgis -U admin "$db_name"
    pg_restore -h postgis -U admin --no-owner --role=admin -d "$db_name" "$dump_file"
  fi
done

echo "All dumps processed."

# Create TXFull if it doesn't exist
echo "Checking if database TXFull exists..."
if psql -h postgis -U admin -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'TXFull'" | grep -q 1; then
  echo "Database TXFull exists. Skipping creation..."
else
  echo "Creating database TXFull..."
  createdb -h postgis -U admin TXFull
fi

# Run alter_tables.sh before setting up TXFull
echo "Running table alterations to include primary key..."
bash "/postgres_init/alter_existing_dyn_tables.sh"

# Run SQL scripts in TXFull
echo "Running SQL scripts in TXFull..."
psql -h postgis -U admin -d TXFull -f /postgres_init/create_foreign_data_views.sql
psql -h postgis -U admin -d TXFull -f /postgres_init/create_merged_view.sql
psql -h postgis -U admin -d TXFull -f /postgres_init/create_merged_materialized_view.sql

echo "TXFull database setup completed."
