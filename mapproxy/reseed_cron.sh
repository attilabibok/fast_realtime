#!/bin/bash
echo "Starting hourly reseed..."

while true; do
    /usr/local/bin/mapproxy-seed -f /mapproxy/mapproxy.yaml -s /mapproxy/seed.yaml hourly_seed
    sleep 3600
done
