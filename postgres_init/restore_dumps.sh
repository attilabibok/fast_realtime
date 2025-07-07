#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be available on postgis:5432..."
until pg_isready -h postgis -p 5432 -U admin; do
  sleep 2
done

echo "PostgreSQL is ready. Checking and restoring dumps..."

for dump_file in /dumps/*.dump; do
  [ -e "$dump_file" ] || continue

  db_name=$(basename "$dump_file" _realtime_hand.dump | cut -d_ -f2)

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

# Run SQL scripts in TXFull
echo "Running SQL scripts in TXFull..."
psql -h postgis -U admin -d TXFull -f /docker-entrypoint-initdb.d/create_foreign_data_views.sql
psql -h postgis -U admin -d TXFull -f /docker-entrypoint-initdb.d/create_merged_view.sql
psql -h postgis -U admin -d TXFull -f /docker-entrypoint-initdb.d/create_merged_materialized_view.sql

echo "TXFull database setup completed."
