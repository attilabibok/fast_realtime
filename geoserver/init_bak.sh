#!/usr/bin/env bash
set -euo pipefail

GEOSERVER_URL="${GEOSERVER_URL:-http://localhost:8080/geoserver}"
AUTH="${GEOSERVER_AUTH:-admin:geoserver}"

PG_HOST="${PG_HOST:-postgis}"
PG_PORT="${PG_PORT:-5432}"
PG_DB="${PG_DB:-TXFull}"
PG_USER="${PG_USER:-admin}"
PG_PASS="${PG_PASS:-admin123}"

WORKSPACE="${WORKSPACE:-txdot}"
STORE_NAME="${STORE_NAME:-txfull_pg}"
SRS="${SRS:-EPSG:4326}"

# Publish exactly these workflows:
WORKFLOWS="${WORKFLOWS:-ds_sr da_sr_nc nwm_sr nwm_sr_nc}"

# Districts: id shortcode schema
DISTRICTS="$(cat <<'EOF'
01 PAR foreign_01
02 FTW foreign_02
03 WFS foreign_03
04 AMA foreign_04
05 LBB foreign_05
06 ODA foreign_06
07 SJT foreign_07
08 ABL foreign_08
09 WAC foreign_09
10 TYL foreign_10
11 LFK foreign_11
12 HOU foreign_12
13 YKM foreign_13
14 AUS foreign_14
15 SAT foreign_15
16 CRP foreign_16
17 BRY foreign_17
18 DAL foreign_18
19 ATL foreign_19
20 BMT foreign_20
21 PHR foreign_21
22 LRD foreign_22
23 BWD foreign_23
24 ELP foreign_24
25 CHS foreign_25
EOF
)"

# --- Wait for GeoServer ---
until curl -s -u "$AUTH" "$GEOSERVER_URL/rest/about/version.json" >/dev/null; do
  echo "Waiting for GeoServer..."
  sleep 5
done

# --- Workspace ---
if ! curl -s -u "$AUTH" "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}.xml" | grep -q "<name>${WORKSPACE}</name>"; then
  curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d "<workspace><name>${WORKSPACE}</name></workspace>" \
    "$GEOSERVER_URL/rest/workspaces"
fi

# --- Style for flood polygons (optional, if provided) ---
if ! curl -s -u "$AUTH" "$GEOSERVER_URL/rest/styles/floodstyle.xml" | grep -q "<name>floodstyle</name>"; then
  if [[ -s /floodstyle.sld ]]; then
    curl -s -u "$AUTH" -XPOST "$GEOSERVER_URL/rest/styles" \
      -H "Content-type: application/xml" \
      -d "<style><name>floodstyle</name><filename>floodstyle.sld</filename></style>"
    curl -s -u "$AUTH" -XPUT "$GEOSERVER_URL/rest/styles/floodstyle" \
      -H "Content-type: application/vnd.ogc.sld+xml" \
      --data-binary "@/floodstyle.sld"
  fi
fi

# --- Single datastore to TXFull ---
DATASTORE_URL="$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores/${STORE_NAME}.xml"
if ! curl -s -u "$AUTH" "$DATASTORE_URL" | grep -q "<name>${STORE_NAME}</name>"; then
  cat > /tmp/${STORE_NAME}.xml <<EOF
<dataStore>
  <name>${STORE_NAME}</name>
  <connectionParameters>
    <entry key="dbtype">postgis</entry>
    <entry key="host">${PG_HOST}</entry>
    <entry key="port">${PG_PORT}</entry>
    <entry key="database">${PG_DB}</entry>
    <entry key="user">${PG_USER}</entry>
    <entry key="passwd">${PG_PASS}</entry>
    <entry key="schema">public</entry>
    <entry key="Expose primary keys">true</entry>
    <entry key="Loose bbox">true</entry>
  </connectionParameters>
</dataStore>
EOF
  curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d @/tmp/${STORE_NAME}.xml \
    "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores"
fi

# --- Helper: SQL view (JDBC virtual table) publisher ---
create_sqlview_layer () {
  local layer_name="$1"
  local sql="$2"
  local key_col="$3"
  local title="$4"
  local default_style="${5:-}"

  # Skip if already exists
  if curl -s -u "$AUTH" "$GEOSERVER_URL/rest/layers/${WORKSPACE}:${layer_name}.xml" | grep -q "<name>${layer_name}</name>"; then
    return 0
  fi

  cat > /tmp/${layer_name}.xml <<EOF
<featureType>
  <name>${layer_name}</name>
  <nativeName>${layer_name}</nativeName>
  <title>${title}</title>
  <srs>${SRS}</srs>
  <metadata>
    <entry key="JDBC_VIRTUAL_TABLE">
      <virtualTable>
        <name>${layer_name}</name>
        <sql>${sql}</sql>
        <escapeSql>false</escapeSql>
        <keyColumn>${key_col}</keyColumn>
        <geometry>
          <name>geometry</name>
          <type>Geometry</type>
          <srid>${SRS#EPSG:}</srid>
        </geometry>
      </virtualTable>
    </entry>
  </metadata>
</featureType>
EOF

  curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d @/tmp/${layer_name}.xml \
    "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores/${STORE_NAME}/featuretypes"

  if [[ -n "$default_style" ]]; then
    curl -s -u "$AUTH" -XPUT \
      -H "Content-type: application/xml" \
      -d "<layer><defaultStyle><name>${default_style}</name></defaultStyle></layer>" \
      "$GEOSERVER_URL/rest/layers/${WORKSPACE}:${layer_name}"
  fi
}

# --- 1) TX-wide (materialized views) per workflow ---
# From your SQL: mv_flood_merge_tx, mv_flood_road_trim_ln_tx, mv_bridge_warning_pnt_tx
# (Each carries geometry + workflow_id)  :contentReference[oaicite:1]{index=1}
for WF in ${WORKFLOWS}; do
  create_sqlview_layer \
    "${WF}_tx_flood" \
    "SELECT tile_id_tx AS id, geometry, model_run_time, workflow_id, source_db
    FROM public.mv_flood_merge_tx
    WHERE COALESCE(workflow_id,'default')='${WF}'" \
    "id" "TX Flood Merge (wf=${WF})" "floodstyle"

  create_sqlview_layer \
    "${WF}_tx_roads" \
    "SELECT road_id_tx AS id, geometry, tile_id, max_flow, length_ft, workflow_id
    FROM public.mv_flood_road_trim_ln_tx
    WHERE COALESCE(workflow_id,'default')='${WF}'" \
    "id" "TX Flooded Roads (wf=${WF})"

  create_sqlview_layer \
    "${WF}_tx_bridges" \
    "SELECT bridge_idx_tx AS id, geometry, \"BRDG_ID\", name, ref, nhd_name, is_overtop,
            min_dist_to_low_ch, model_run_time, url, workflow_id, source_db
    FROM public.mv_bridge_warning_pnt_tx
    WHERE COALESCE(workflow_id,'default')='${WF}'" \
    "id" "TX Bridge Warnings (wf=${WF})"
done

# --- 2) Per-district tables per workflow (schema-qualified) ---
while read -r DID DCODE SCHEMA; do
  for WF in ${WORKFLOWS}; do
    # Flood polygons
    create_sqlview_layer \
      "${WF}_${DCODE}_flood" \
      "SELECT (tile_id::text || '_' || COALESCE(workflow_id,'default')) AS id,
              geometry, model_run_time, workflow_id
      FROM ${SCHEMA}.s_flood_merge_ar
      WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Flood Merge (wf=${WF})" "floodstyle"

    # Flooded roads
    create_sqlview_layer \
      "${WF}_${DCODE}_roads" \
      "SELECT (road_id::text || '_' || COALESCE(workflow_id,'default')) AS id,
              geometry, tile_id, max_flow, length_ft, workflow_id, name, ref, fclass
      FROM ${SCHEMA}.s_flood_road_trim_ln
      WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Flooded Roads (wf=${WF})"

    # Bridge warnings
    create_sqlview_layer \
      "${WF}_${DCODE}_bridges" \
      "SELECT (COALESCE(\"BRDG_ID\",'') || '_' || row_number() OVER ()) AS id,
              geometry, \"BRDG_ID\", name, ref, nhd_name, is_overtop, min_dist_to_low_ch,
              model_run_time, url, workflow_id
      FROM ${SCHEMA}.s_bridge_warning_pnt
      WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Bridge Warnings (wf=${WF})"

  done
done <<< "${DISTRICTS}"

# --- 3) Layer groups per workflow (TX-wide) ---
# Each group = Flood + Roads + Bridges for a workflow (order matches typical draw order)
for WF in ${WORKFLOWS}; do
  LG="${WORKSPACE}:tx__wf_${WF}"
  if ! curl -s -u "$AUTH" "$GEOSERVER_URL/rest/layergroups/${LG#${WORKSPACE}:}.xml?workspace=${WORKSPACE}" \
       | grep -q "<name>${LG#${WORKSPACE}:}</name>"; then
    cat > /tmp/${LG#${WORKSPACE}:}.xml <<EOF
<layerGroup>
  <name>${LG#${WORKSPACE}:}</name>
  <mode>SINGLE</mode>
  <publishables>
    <published type="layer"><name>${WORKSPACE}:tx_mv_flood_merge__wf_${WF}</name></published>
    <published type="layer"><name>${WORKSPACE}:tx_mv_flood_roads__wf_${WF}</name></published>
    <published type="layer"><name>${WORKSPACE}:tx_mv_bridge_warn__wf_${WF}</name></published>
  </publishables>
</layerGroup>
EOF
    curl -s -u "$AUTH" -XPOST -H "Content-type: text/xml" \
      -d @/tmp/${LG#${WORKSPACE}:}.xml \
      "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/layergroups"
  fi
done

echo ">>> GeoServer publishing complete (workflows: ${WORKFLOWS})"
