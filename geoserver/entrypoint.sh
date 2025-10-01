#!/bin/bash
set -euo pipefail

# Start GeoServer in the background
catalina.sh run &

# Wait for GeoServer to be available
until curl -s -u admin:geoserver http://localhost:8080/geoserver/rest/about/version.json >/dev/null; do
  echo "Waiting for GeoServer..."
  sleep 5
done

echo "GeoServer is up — running init…"
# Run the init with xtrace for visibility
bash -x /init.sh || { echo "Init failed"; exit 1; }

# Keep container alive on Tomcat
wait -n
