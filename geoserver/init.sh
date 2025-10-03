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

# 6.0 Remove masterpw.info warning file if present
if [ -f /opt/geoserver/data_dir/security/masterpw.info ]; then
  echo "Removing security/masterpw.info (security risk warning)…"
  rm -f /opt/geoserver/data_dir/security/masterpw.info || true
fi

# 6.1 Ensure a 'viewer' user exists (password from env). This user will be READ-ONLY.
if ! curl -fsS -u "$AUTH" \
    "$GEOSERVER_URL/rest/security/usergroup/service/default/users/${VIEWER_USER}.json" >/dev/null 2>&1; then
  curl -fsS -u "$AUTH" -X POST -H "Content-Type: application/json" \
    -d "{\"user\":{\"userName\":\"${VIEWER_USER}\",\"password\":\"${VIEWER_PASS}\",\"enabled\":true}}" \
    "$GEOSERVER_URL/rest/security/usergroup/service/default/users" >/dev/null || true
  echo "Created user '${VIEWER_USER}'"
fi

# 6.2 Create a dedicated ROLE_VIEWER and assign it to 'viewer' (idempotent)
curl -fsS -u "$AUTH" -X POST \
  "$GEOSERVER_URL/rest/roles/role/ROLE_VIEWER" >/dev/null 2>&1 || true
curl -fsS -u "$AUTH" -X POST \
  "$GEOSERVER_URL/rest/roles/role/ROLE_VIEWER/user/${VIEWER_USER}/" >/dev/null 2>&1 || true

# 6.2.b Ensure viewer is NOT admin (safe even if not present)
curl -fsS -u "$AUTH" -X DELETE \
  "$GEOSERVER_URL/rest/roles/role/ADMIN/user/${VIEWER_USER}/" >/dev/null 2>&1 || true
curl -fsS -u "$AUTH" -X DELETE \
  "$GEOSERVER_URL/rest/roles/role/GROUP_ADMIN/user/${VIEWER_USER}/" >/dev/null 2>&1 || true

# 6.3 Layer ACLs: READ for anonymous + ROLE_VIEWER, WRITE/ADMIN for ADMIN only
# If you do NOT want public access, remove ROLE_ANONYMOUS below.
cat >/tmp/acl_layers.xml <<'XML'
<rules>
  <!-- READ for public (anonymous) and logged-in viewer role -->
  <rule resource="*.*.r">ROLE_ANONYMOUS,ROLE_VIEWER</rule>

  <!-- WRITE & ADMIN restricted to admins only -->
  <rule resource="*.*.w">ADMIN</rule>
  <rule resource="*.*.a">ADMIN</rule>
</rules>
XML
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  --data-binary @/tmp/acl_layers.xml \
  "$GEOSERVER_URL/rest/security/acl/layers.xml" >/dev/null || true

# 6.4 Service ACLs:
# - WMS and non-transactional WFS allowed to public+viewer
# - WFS Transaction (WFS-T) locked to ADMIN
# - WPS entirely locked to ADMIN
cat >/tmp/acl_services.xml <<'XML'
<rules>
  <rule resource="wms.*">ROLE_ANONYMOUS,ROLE_VIEWER</rule>
  <rule resource="wfs.*">ROLE_ANONYMOUS,ROLE_VIEWER</rule>
  <rule resource="wfs.Transaction">ADMIN</rule>
  <rule resource="wps.*">ADMIN</rule>
</rules>
XML
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  --data-binary @/tmp/acl_services.xml \
  "$GEOSERVER_URL/rest/security/acl/services.xml" >/dev/null || true

# 6.5 (Optional #1) Force WFS to read-only at service level (belt-and-suspenders)
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  -d '<wfs><serviceLevel>Basic</serviceLevel></wfs>' \
  "$GEOSERVER_URL/rest/services/wfs/settings" >/dev/null || true

# 6.6 (Optional #2) Hide secured resources from capabilities for non-authorized users
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  -d '<catalog><mode>HIDE</mode></catalog>' \
  "$GEOSERVER_URL/rest/security/acl/catalog.xml" >/dev/null || true

# 6.7 Ensure desired admin (via env) — ONLY if factory admin works
# Env inputs:
#   DESIRED_ADMIN_USER (e.g., admin | txdot_admin)
#   DESIRED_ADMIN_PASS (e.g., txdot_geoserver | SuperSecret123)
_desired_admin="${DESIRED_ADMIN_USER:-admin}"
_desired_pass="${DESIRED_ADMIN_PASS:-geoserver}"

if _has_creds "admin:geoserver"; then
  echo "[security] Factory admin available; applying desired admin settings from env…"

  if [[ "${_desired_admin}" == "admin" ]]; then
    # Rotate admin password to desired value (idempotent)
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
    # Create/enable the desired admin user, grant ADMIN (idempotent)
    curl -fsS -u admin:geoserver -X POST -H "Content-Type: application/json" \
      -d "{\"user\":{\"userName\":\"${_desired_admin}\",\"password\":\"${_desired_pass}\",\"enabled\":true}}" \
      "${GEOSERVER_URL}/rest/security/usergroup/users" >/dev/null 2>&1 || true

    curl -fsS -u admin:geoserver -X POST \
      "${GEOSERVER_URL}/rest/security/roles/role/ADMIN/user/${_desired_admin}" >/dev/null 2>&1 || true

    # Switch AUTH to the desired admin if it authenticates
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

# 6.8 Disable factory 'admin' — only if we created a non-'admin' desired admin and can auth as it
if [[ "${_desired_admin}" != "admin" ]] && _has_creds "${_desired_admin}:${_desired_pass}"; then
  curl -fsS -u "${_desired_admin}:${_desired_pass}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"user":{"userName":"admin","enabled":false}}' \
    "${GEOSERVER_URL}/rest/security/usergroup/user/admin" >/dev/null 2>&1 || true
  echo "[security] Factory 'admin' account disabled."
else
  echo "[security] Skipping disable of factory 'admin' (either desired admin is 'admin' or cannot auth)."
fi

# 6.9 Further hardening to make it prod-ready

# 6.9.1 Switch default User/Group service to Digest (idempotent-ish)
# Find the default U/G service name:
UGS_NAME="$(curl -fsS -u "$AUTH" -H "Accept: application/json" \
  "$GEOSERVER_URL/rest/security/usergroupservices" \
  | jq -r '..|.name? // empty' | head -n1)"

if [ -n "$UGS_NAME" ]; then
  tmpfile="$(mktemp)"
  curl -fsS -u "$AUTH" -H "Accept: application/json" \
    "$GEOSERVER_URL/rest/security/usergroupservices/${UGS_NAME}" > "$tmpfile" || true

  if grep -q '"passwordEncoderName"' "$tmpfile"; then
    if ! grep -q '"passwordEncoderName":[[:space:]]*"digestPasswordEncoder"' "$tmpfile"; then
      jq '(.["org.geoserver.security.xml.XMLUserGroupServiceConfig"].passwordEncoderName // .passwordEncoderName)="digestPasswordEncoder"' \
        "$tmpfile" > "${tmpfile}.new" 2>/dev/null || cp "$tmpfile" "${tmpfile}.new"
      curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/json" \
        -d @"${tmpfile}.new" \
        "$GEOSERVER_URL/rest/security/usergroupservices/${UGS_NAME}" >/dev/null || true
      echo "Set User/Group service '${UGS_NAME}' password encoder to Digest."
      echo "NOTE: Recode existing user passwords via UI: Security → Users, Groups, Roles → default → Passwords."
    fi
  fi
  rm -f "$tmpfile" "${tmpfile}.new" 2>/dev/null || true
fi

# 6.9.2 CSRF whitelist and hide FS outside data dir (useful in containers/proxies)
: "${GEOSERVER_CSRF_WHITELIST:=}"  # supply as env in Compose/K8s
: "${GEOSERVER_FILEBROWSER_HIDEFS:=true}"
export GEOSERVER_FILEBROWSER_HIDEFS

# 6.9.3 (Optional) Make WFS read-only and keep WPS admin-only
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  -d '<wfs><serviceLevel>Basic</serviceLevel></wfs>' \
  "$GEOSERVER_URL/rest/services/wfs/settings" >/dev/null || true

cat >/tmp/acl_services.xml <<'XML'
<rules>
  <rule resource="wms.*">ROLE_ANONYMOUS,ROLE_VIEWER</rule>
  <rule resource="wfs.*">ROLE_ANONYMOUS,ROLE_VIEWER</rule>
  <rule resource="wfs.Transaction">ADMIN</rule>
  <rule resource="wps.*">ADMIN</rule>
</rules>
XML
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/xml" \
  --data-binary @/tmp/acl_services.xml \
  "$GEOSERVER_URL/rest/security/acl/services.xml" >/dev/null || true

# 6.x.4 (Optional) Switch logging to PRODUCTION via REST
# (You can also do this under Settings → Global → Logging profile)
cat >/tmp/logging.json <<'JSON'
{"logging":{"level":"DEFAULT_LOGGING","stdOutLogging":"false","location":"logs/geoserver.log","profiler":"PRODUCTION_LOGGING"}}
JSON
curl -fsS -u "$AUTH" -X PUT -H "Content-Type: application/json" \
  -d @/tmp/logging.json \
  "$GEOSERVER_URL/rest/logging" >/dev/null || true