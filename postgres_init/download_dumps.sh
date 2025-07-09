#!/bin/bash
set -e

echo "Downloading dumps to /dumps..."
BASE_URL="https://web.corral.tacc.utexas.edu/nfiedata/acarter/roadflood-db-20250702"
TARGET_DIR="/dumps"

# Make sure the target directory exists
mkdir -p "${TARGET_DIR}"

# List of dump files
files=(
    "01_PAR_realtime_hand.dump"
    "02_FTW_realtime_hand.dump"
    "04_AMA_realtime_hand.dump"
    "06_ODA_realtime_hand.dump"
    "07_SJT_realtime_hand.dump"
    "08_ABL_realtime_hand.dump"
    "11_LFK_realtime_hand.dump"
    "13_YKM_realtime_hand.dump"
    "14_AUS_realtime_hand.dump"
    "15_SAT_realtime_hand.dump"
    "16_CRP_realtime_hand.dump"
    "17_BRY_realtime_hand.dump"
    "18_DAL_realtime_hand.dump"
    "19_ATL_realtime_hand.dump"
    "20_BMT_realtime_hand.dump"
    "21_PHR_realtime_hand.dump"
    "23_BWD_realtime_hand.dump"
    "24_ELP_realtime_hand.dump"
    "25_CHS_realtime_hand.dump"
)

for file in "${files[@]}"; do
    echo "Downloading ${file}..."
    curl -fSL "${BASE_URL}/${file}" -o "${TARGET_DIR}/${file}"
done

echo "All dumps downloaded successfully."