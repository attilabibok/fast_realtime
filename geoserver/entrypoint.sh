#!/bin/bash

# Start GeoServer in the background using the default CMD
catalina.sh run &

# Wait for GeoServer to be available
until curl -s -u admin:geoserver http://localhost:8080/geoserver/rest/about/version.json >/dev/null; do
  echo "Waiting for GeoServer..."
  sleep 5
done

# Run the init script
bash /init.sh

# Tail logs to keep container running
wait -n
