#!/bin/bash
echo ">>> INIT SCRIPT RUNNING" > /opt/geoserver/data_dir/started.txt
set -euo pipefail

GEOSERVER_URL="http://localhost:8080/geoserver"
AUTH="admin:geoserver"

databases=(
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

# Wait for GeoServer to start
until curl -s -u "$AUTH" "$GEOSERVER_URL/rest/about/version.json" > /dev/null; do
  echo "Waiting for GeoServer to become ready..."
  sleep 5
done

# Create workspace if it doesn't exist
if ! curl -s -u "$AUTH" "$GEOSERVER_URL/rest/workspaces/txdot" | grep -q "<name>txdot</name>"; then
  curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d "<workspace><name>txdot</name></workspace>" \
    "$GEOSERVER_URL/rest/workspaces"
fi

# Upload style if it doesn't exist
if ! curl -s -u "$AUTH" "$GEOSERVER_URL/rest/styles/floodstyle" | grep -q "floodstyle"; then
  if [[ -s /floodstyle.sld ]]; then
    echo "Uploading floodstyle.sld metadata..."
    curl -s -u "$AUTH" -XPOST "$GEOSERVER_URL/rest/styles" \
      -H "Content-type: application/xml" \
      -d "<style><name>floodstyle</name><filename>floodstyle.sld</filename></style>"

    echo "Uploading actual floodstyle.sld content..."
    curl -s -u "$AUTH" -XPUT "$GEOSERVER_URL/rest/styles/floodstyle" \
      -H "Content-type: application/vnd.ogc.sld+xml" \
      --data-binary "@/floodstyle.sld"
  else
    echo "Error: /floodstyle.sld is missing or empty"
  fi
fi

# Loop over each DB
for db in "${databases[@]}"; do
  echo "Configuring GeoServer store and layer for DB: $db"

  store_name="txdot_pg_${db}"
  layer_name="s_flood_merge_ar_${db}"
  native_name="s_flood_merge_ar"

  # Create datastore if not exists
  store_url="$GEOSERVER_URL/rest/workspaces/txdot/datastores/${store_name}.xml"
  if ! curl -s -u "$AUTH" "$store_url" | grep -q "<name>${store_name}</name>"; then
    cat <<EOF > /tmp/${db}_store.xml
<dataStore>
  <name>${store_name}</name>
  <connectionParameters>
    <entry key="host">postgis</entry>
    <entry key="port">5432</entry>
    <entry key="database">${db}</entry>
    <entry key="user">admin</entry>
    <entry key="passwd">admin123</entry>
    <entry key="dbtype">postgis</entry>
    <entry key="Expose primary keys">true</entry>
  </connectionParameters>
</dataStore>
EOF

    curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
      -d @/tmp/${db}_store.xml \
      "$GEOSERVER_URL/rest/workspaces/txdot/datastores"
  fi

  # Create layer if not exists
  layer_url="$GEOSERVER_URL/rest/layers/txdot:${layer_name}.xml"
  if ! curl -s -u "$AUTH" "$layer_url" | grep -q "<name>${layer_name}</name>"; then
    cat <<EOF > /tmp/${db}_layer.xml
<featureType>
  <name>${layer_name}</name>
  <nativeName>${native_name}</nativeName>
  <title>${db} Flood Merge</title>
  <srs>EPSG:4326</srs>
</featureType>
EOF

    curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
      -d @/tmp/${db}_layer.xml \
      "$GEOSERVER_URL/rest/workspaces/txdot/datastores/${store_name}/featuretypes"
  fi

  # Assign style
  curl -s -u "$AUTH" -XPUT "$GEOSERVER_URL/rest/layers/txdot:${layer_name}" \
  -H "Content-type: application/xml" \
  -d "<layer><defaultStyle><name>floodstyle</name></defaultStyle></layer>"
done

echo ">>> Init script completed."
