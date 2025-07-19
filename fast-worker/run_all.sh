#!/bin/bash
set -e

# Use environment variables or fallback to defaults (relative to /fast_realtime/src)
INI_DIR="${INI_DIR:-/fast_realtime/src/txdot_dist_local}"
SCRIPT="${SCRIPT:-/fast_realtime/src/fast_realtime_update.py}"

echo "Running worker loop over all .ini files in $INI_DIR"
echo "--------------------------------------------------"

for ini_file in "$INI_DIR"/config_*.ini; do
  district=$(basename "$ini_file" .ini | cut -d'_' -f2-3)
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting: $district"
  
  start=$(date +%s)
  python "$SCRIPT" -c "$ini_file"
  end=$(date +%s)

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finished: $district in $((end - start))s"
  echo "--------------------------------------------------"
done