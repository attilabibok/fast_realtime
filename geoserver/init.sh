#!/usr/bin/env bash
set -euo pipefail

# ================================
# Environment & defaults
# ================================
GEOSERVER_URL="${GEOSERVER_URL:-http://localhost:8080/geoserver}"
# GEOSERVER_AUTH is the "desired" admin you want active after bootstrap.
# e.g. admin:txdot or txdot_admin:superSecret
AUTH="${GEOSERVER_AUTH:-admin:geoserver}"

PG_HOST="${PG_HOST:-postgis}"
PG_PORT="${PG_PORT:-5432}"
PG_DB="${PG_DB:-TXFull}"
PG_USER="${PG_USER:-admin}"
PG_PASS="${PG_PASS:-admin123}"

WORKSPACE="${WORKSPACE:-txdot}"
STORE_NAME="${STORE_NAME:-txfull_pg}"
SRS="${SRS:-EPSG:4326}"

WORKFLOWS="${WORKFLOWS:-ds_sr da_sr_nc nwm_sr nwm_sr_nc}"

VIEWER_USER="${VIEWER_USER:-viewer}"
VIEWER_PASS="${VIEWER_PASS:-txdot}"

# Districts
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

# Strip accidental quotes in env (compose quirks)
strip_quotes() { sed -E "s/^'(.*)'\$/\1/; s/^\"(.*)\"\$/\1/"; }
for v in GEOSERVER_URL AUTH PG_HOST PG_PORT PG_DB PG_USER PG_PASS WORKSPACE STORE_NAME SRS WORKFLOWS VIEWER_USER VIEWER_PASS; do
  eval "export $v=\"\$(printf %s \"\${$v}\" | strip_quotes)\""
done

# Derive desired admin user/pass from AUTH unless explicitly overridden
DESIRED_ADMIN_USER="${DESIRED_ADMIN_USER:-${AUTH%%:*}}"
DESIRED_ADMIN_PASS="${DESIRED_ADMIN_PASS:-${AUTH#*:}}"

# ================================
# Wait for GeoServer webapp and for REST to stop returning 5xx
# ================================
until curl -fsS "${GEOSERVER_URL}/web/" >/dev/null 2>&1; do
  echo "Waiting for GeoServer web UI…"
  sleep 2
done
# ================================
# Wait for PostGIS to start
# ================================
wait_pg() {
  local tries=60
  while (( tries-- > 0 )); do
    (exec 3<>/dev/tcp/"$PG_HOST"/"$PG_PORT") >/dev/null 2>&1 && { exec 3>&- 3<&-; return 0; }
    sleep 1
  done
  echo "[FATAL] PG $PG_HOST:$PG_PORT not reachable after 60s" >&2
  exit 1
}
wait_pg
# wait_rest_ready() {
#   local tries="${1:-100}" code
#   while (( tries-- > 0 )); do
#     code="$(curl -s -o /dev/null -w '%{http_code}' \
#             -H 'Accept: application/xml' \
#             "${GEOSERVER_URL}/rest/about/version" || echo 000)"
#     case "$code" in
#       200|401|403) return 0 ;;
#     esac
#     # alternate probe (HTML)
#     code="$(curl -s -o /dev/null -w '%{http_code}' \
#             "${GEOSERVER_URL}/rest/about/system-status.html" || echo 000)"
#     case "$code" in
#       200|401|403) return 0 ;;
#     esac
#     sleep 3
#   done
#   echo "[FATAL] GeoServer REST still unhealthy. Check container logs." >&2
#   exit 1
# }
# wait_rest_ready

# ================================
# Helpers
# ================================
probe_backoff() {
  local creds="$1"; local tries="${2:-10}"; local delay="${3:-1}"
  while (( tries > 0 )); do
    local code; code="$(curl -s -o /dev/null -w "%{http_code}" -u "$creds" \
      "$GEOSERVER_URL/rest/about/version.json" || echo 000)"
    if [[ "$code" == "200" ]]; then
      return 0
    fi
    sleep "$delay"
    (( delay < 20 )) && delay=$((delay*2))
    (( tries-- ))
  done
  return 1
}

# Safe XML "exists" check
exists_xml() {
  local url="$1"
  curl -fsS -u "$AUTH" "$url" | grep -q "<name>"
}
# ================================
# 0) Bootstrap admin - leave defaults
# ================================
AUTH="${AUTH:-admin:geoserver}"   # ensure AUTH is set
echo "[bootstrap] Using factory default credentials for this run: ${AUTH}"
if ! probe_backoff "$AUTH"; then
  echo "[FATAL] Cannot authenticate with default admin:geoserver; is GeoServer healthy?" >&2
  exit 1
fi

# ================================
# 1) Workspace & Style
# ================================
if ! curl -fsS -u "$AUTH" "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}.xml" | grep -q "<name>${WORKSPACE}</name>"; then
  curl -fsS -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d "<workspace><name>${WORKSPACE}</name></workspace>" \
    "$GEOSERVER_URL/rest/workspaces" >/dev/null
fi

if ! curl -fsS -u "$AUTH" "$GEOSERVER_URL/rest/styles/floodstyle.xml" | grep -q "<name>floodstyle</name>"; then
  if [[ -s /floodstyle.sld ]]; then
    curl -fsS -u "$AUTH" -XPOST "$GEOSERVER_URL/rest/styles" \
      -H "Content-type: application/xml" \
      -d "<style><name>floodstyle</name><filename>floodstyle.sld</filename></style>" >/dev/null
    curl -fsS -u "$AUTH" -XPUT "$GEOSERVER_URL/rest/styles/floodstyle" \
      -H "Content-type: application/vnd.ogc.sld+xml" \
      --data-binary "@/floodstyle.sld" >/dev/null
  fi
fi

# ================================
# 2) Datastore (PostGIS)
# ================================
DATASTORE_URL="$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores/${STORE_NAME}.xml"
if ! curl -fsS -u "$AUTH" "$DATASTORE_URL" | grep -q "<name>${STORE_NAME}</name>"; then
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
  curl -fsS -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d @/tmp/${STORE_NAME}.xml \
    "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores" >/dev/null
fi

# ================================
# 3) Publisher helpers
# ================================
create_sqlview_layer () {
  local layer_name="$1"
  local sql="$2"
  local key_col="$3"
  local title="$4"
  local default_style="${5:-}"

  # Already exists?
  if curl -fsS -u "$AUTH" "$GEOSERVER_URL/rest/layers/${WORKSPACE}:${layer_name}.xml" | grep -q "<name>${layer_name}</name>"; then
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

  curl -fsS -u "$AUTH" -XPOST -H "Content-type: text/xml" \
    -d @/tmp/${layer_name}.xml \
    "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/datastores/${STORE_NAME}/featuretypes" >/dev/null

  if [[ -n "$default_style" ]]; then
    curl -fsS -u "$AUTH" -XPUT \
      -H "Content-type: application/xml" \
      -d "<layer><defaultStyle><name>${default_style}</name></defaultStyle></layer>" \
      "$GEOSERVER_URL/rest/layers/${WORKSPACE}:${layer_name}" >/dev/null
  fi
}

# ================================
# 4) Publish layers (TX-wide + per-district) filtered by workflow_id
# ================================
for WF in ${WORKFLOWS}; do
  # TX-wide
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

  # Per district
  while read -r DID DCODE SCHEMA; do
    create_sqlview_layer \
      "${WF}_${DCODE}_flood" \
      "SELECT (tile_id::text || '_' || COALESCE(workflow_id,'default')) AS id,
              geometry, model_run_time, workflow_id
       FROM ${SCHEMA}.s_flood_merge_ar
       WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Flood Merge (wf=${WF})" "floodstyle"

    create_sqlview_layer \
      "${WF}_${DCODE}_roads" \
      "SELECT (road_id::text || '_' || COALESCE(workflow_id,'default')) AS id,
              geometry, tile_id, max_flow, length_ft, workflow_id, name, ref, fclass
       FROM ${SCHEMA}.s_flood_road_trim_ln
       WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Flooded Roads (wf=${WF})"

    create_sqlview_layer \
      "${WF}_${DCODE}_bridges" \
      "SELECT (COALESCE(\"BRDG_ID\",'') || '_' || row_number() OVER ()) AS id,
              geometry, \"BRDG_ID\", name, ref, nhd_name, is_overtop, min_dist_to_low_ch,
              model_run_time, url, workflow_id
       FROM ${SCHEMA}.s_bridge_warning_pnt
       WHERE COALESCE(workflow_id,'default')='${WF}'" \
      "id" "${DCODE} Bridge Warnings (wf=${WF})"
  done <<< "${DISTRICTS}"
done

# ================================
# 5) Layer groups (per workflow)
# ================================
for WF in ${WORKFLOWS}; do
  LG_NAME="${WF}_tx"
  if ! curl -fsS -u "$AUTH" "$GEOSERVER_URL/rest/layergroups/${LG_NAME}.xml?workspace=${WORKSPACE}" \
       | grep -q "<name>${LG_NAME}</name>"; then
    cat > /tmp/${LG_NAME}.xml <<EOF
<layerGroup>
  <name>${LG_NAME}</name>
  <mode>SINGLE</mode>
  <layers>
    <layer>${WF}_tx_flood</layer>
    <layer>${WF}_tx_roads</layer>
    <layer>${WF}_tx_bridges</layer>
  </layers>
  <styles>
    <style/>
    <style/>
    <style/>
  </styles>
  <publishables>
    <published type="layer"><name>${WORKSPACE}:${WF}_tx_flood</name></published>
    <published type="layer"><name>${WORKSPACE}:${WF}_tx_roads</name></published>
    <published type="layer"><name>${WORKSPACE}:${WF}_tx_bridges</name></published>
  </publishables>
</layerGroup>
EOF
    curl -fsS -u "$AUTH" -XPOST -H "Content-type: text/xml" \
      -d @/tmp/${LG_NAME}.xml \
      "$GEOSERVER_URL/rest/workspaces/${WORKSPACE}/layergroups" >/dev/null
  fi
done

echo ">>> GeoServer publishing complete (workflows: ${WORKFLOWS})"
# ================================
# 6) Security hardening (read-only viewer + public read) — idempotent
# ================================

# helper: quick auth probe for specific creds (returns 0 if OK)
_has_creds() {
  local creds="$1"
  probe_backoff "$creds" 3 1 >/dev/null 2>&1
}

# remove masterpw warning if present
if [ -f /opt/geoserver/data_dir/security/masterpw.info ]; then
  echo "Removing security/masterpw.info (security risk warning)…"
  rm -f /opt/geoserver/data_dir/security/masterpw.info || true
fi

# ensure 'viewer' user exists
if ! curl -fsS -u "$AUTH" \
    "$GEOSERVER_URL/rest/security/usergroup/service/default/users/${VIEWER_USER}.json" >/dev/null 2>&1; then
  curl -fsS -u "$AUTH" -X POST -H "Content-Type: application/json" \
    -d "{\"user\":{\"userName\":\"${VIEWER_USER}\",\"password\":\"${VIEWER_PASS}\",\"enabled\":true}}" \
    "$GEOSERVER_URL/rest/security/usergroup/service/default/users" >/dev/null || true
  echo "Created user '${VIEWER_USER}'"
fi

# ---- roles: use the /rest/security prefix (not /rest/roles)
# create ROLE_VIEWER and assign to viewer (no-op if exist)
curl -fsS -u "$AUTH" -X POST \
  "$GEOSERVER_URL/rest/security/roles/role/ROLE_VIEWER" >/dev/null 2>&1 || true
curl -fsS -u "$AUTH" -X POST \
  "$GEOSERVER_URL/rest/security/roles/role/ROLE_VIEWER/user/${VIEWER_USER}/" >/dev/null 2>&1 || true

# make sure viewer is not admin
curl -fsS -u "$AUTH" -X DELETE \
  "$GEOSERVER_URL/rest/security/roles/role/ADMIN/user/${VIEWER_USER}/" >/dev/null 2>&1 || true
curl -fsS -u "$AUTH" -X DELETE \
  "$GEOSERVER_URL/rest/security/roles/role/GROUP_ADMIN/user/${VIEWER_USER}/" >/dev/null 2>&1 || true

# ---- ACL helpers: POST to create individual rules (avoid 409), then PUT later if needed
_post_acl_rule() {  # _post_acl_rule <which:services|layers> <resource> <roles>
  local which="$1" resource="$2" roles="$3"
  cat >/tmp/_acl_rule.xml <<EOF
<rule><resource>${resource}</resource><roles>${roles}</roles></rule>
EOF
  curl -fsS -u "$AUTH" -X POST -H "Content-Type: application/xml" \
    --data-binary @/tmp/_acl_rule.xml \
    "$GEOSERVER_URL/rest/security/acl/${which}" >/dev/null 2>&1 || true
}

# LAYER ACLs (lower-case pattern semantics handled by GeoServer; these are OK)
# public+viewer READ; admin WRITE/ADMIN (cover both role spellings)
_post_acl_rule layers "*.*.r" "ROLE_ANONYMOUS,ROLE_VIEWER"
_post_acl_rule layers "*.*.w" "ADMIN,ROLE_ADMINISTRATOR"
_post_acl_rule layers "*.*.a" "ADMIN,ROLE_ADMINISTRATOR"

# SERVICE ACLs — **must be lower-case** keys
_post_acl_rule services "wms.*"            "ROLE_ANONYMOUS,ROLE_VIEWER"
_post_acl_rule services "wfs.*"            "ROLE_ANONYMOUS,ROLE_VIEWER"
_post_acl_rule services "ows.*"            "ROLE_ANONYMOUS,ROLE_VIEWER"
_post_acl_rule services "wfs.Transaction"  "ADMIN,ROLE_ADMINISTRATOR"
_post_acl_rule services "wps.*"            "ADMIN,ROLE_ADMINISTRATOR"

# WFS read-only (belt-and-suspenders)
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  -d '<wfs><serviceLevel>Basic</serviceLevel></wfs>' \
  "$GEOSERVER_URL/rest/services/wfs/settings" >/dev/null || true

# Hide secured resources from capabilities
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  -d '<catalog><mode>HIDE</mode></catalog>' \
  "$GEOSERVER_URL/rest/security/acl/catalog.xml" >/dev/null || true

# Ensure desired admin (if factory admin still available)
_desired_admin="${DESIRED_ADMIN_USER:-admin}"
_desired_pass="${DESIRED_ADMIN_PASS:-geoserver}"

if _has_creds "admin:geoserver"; then
  echo "[security] Factory admin available; applying desired admin settings from env…"
  if [[ "${_desired_admin}" == "admin" ]]; then
    if ! _has_creds "admin:${_desired_pass}"; then
      curl -fsS -u admin:geoserver \
        -X PUT -H "Content-Type: application/json" \
        -d "{\"oldPassword\":\"geoserver\",\"newPassword\":\"${_desired_pass}\"}" \
        "${GEOSERVER_URL}/rest/security/self/password" >/dev/null 2>&1 || true
    fi
    if _has_creds "admin:${_desired_pass}"; then
      AUTH="admin:${_desired_pass}"
      echo "[security] 'admin' password is set as desired."
    else
      echo "[security] WARNING: could not verify desired 'admin' password."
    fi
  else
    curl -fsS -u admin:geoserver -X POST -H "Content-Type: application/json" \
      -d "{\"user\":{\"userName\":\"${_desired_admin}\",\"password\":\"${_desired_pass}\",\"enabled\":true}}" \
      "${GEOSERVER_URL}/rest/security/usergroup/users" >/dev/null 2>&1 || true

    curl -fsS -u admin:geoserver -X POST \
      "${GEOSERVER_URL}/rest/security/roles/role/ADMIN/user/${_desired_admin}" >/dev/null 2>&1 || true

    if _has_creds "${_desired_admin}:${_desired_pass}"; then
      AUTH="${_desired_admin}:${_desired_pass}"
      echo "[security] AUTH switched to ${_desired_admin}."
    else
      echo "[security] WARNING: '${_desired_admin}' not yet authenticating with desired password."
    fi
  fi
else
  echo "[security] Skipping desired-admin operations: 'admin:geoserver' not available."
fi

# Disable factory 'admin' if we have a non-admin desired admin that works
if [[ "${_desired_admin}" != "admin" ]] && _has_creds "${_desired_admin}:${_desired_pass}"; then
  curl -fsS -u "${_desired_admin}:${_desired_pass}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"user":{"userName":"admin","enabled":false}}' \
    "${GEOSERVER_URL}/rest/security/usergroup/user/admin" >/dev/null 2>&1 || true
  echo "[security] Factory 'admin' account disabled."
else
  echo "[security] Skipping disable of factory 'admin' (either desired admin is 'admin' or cannot auth)."
fi

# Reload config so ACL + roles take effect right away
curl -fsS -u "$AUTH" -X POST "$GEOSERVER_URL/rest/reload" >/dev/null || true
