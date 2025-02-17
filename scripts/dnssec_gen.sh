#!/usr/bin/env bash
set -eo pipefail
# set -x

TEMP_DIR_BASE="/run/user/$(id -u)"
KEY_DIR_NAME="dnssec-keys-$(date +%Y%m%d%H%M%S)"
TEMP_DIR="${TEMP_DIR_BASE}/${KEY_DIR_NAME}"
ID=""

usage() {
  cat <<EOF

Usage: $0 --id name
  
  Generates DNSSEC KSK, ZSK and AnchorData for resolver and TSIG keys for Knot DNS and outputs them as JSON.
  Ensures temporary Knot database is also in runtime temp and deleted.
EOF
}

cleanup() {
  if test -d "${TEMP_DIR}"; then
    if test -e "${TEMP_DIR}/knot.conf"; then
      cat "${TEMP_DIR}/knot.conf"
    fi
    rm -rf "${TEMP_DIR}"
  fi
}

generate_keys() {
  mkdir -p "${TEMP_DIR}"
  chmod 0700 "${TEMP_DIR}"

  cat > "${TEMP_DIR}/knot.conf" <<EOF
server:
  # No server settings needed for key generation
database:
  storage: ${TEMP_DIR}
# Define a minimal zone
zone:
  - domain: ${ID}
    storage: ${TEMP_DIR}
    journal-content: none
EOF

  # Generate DNSSEC keys
  keymgr -c "${TEMP_DIR}/knot.conf" "${ID}" generate algorithm=ecdsap256sha256 ksk=true
  keymgr -c "${TEMP_DIR}/knot.conf" "${ID}" generate algorithm=ecdsap256sha256 zsk=true
  KSK_DATA="FIXME"
  ZSK_DATA="FIXME"
  ANCHOR_DATA="FIXME"
  
  # Generate TSIG keys
  TRANSFER_SECRET=$(keymgr -t transfer-${ID} hmac-sha256 | grep secret | awk '{print $2}')
  UPDATE_SECRET=$(keymgr -t update-${ID} hmac-sha256 | grep secret | awk '{print $2}')
  NOTIFY_SECRET=$(keymgr -t notify-${ID} hmac-sha256 | grep secret | awk '{print $2}')
  
  # return JSON output
  echo "{"
  echo "  \"ksk\": $(echo "$KSK_DATA" | jq -c .),"
  echo "  \"zsk\": $(echo "$ZSK_DATA" | jq -c .),"
  echo "  \"transfer\": \"${TRANSFER_SECRET}\","
  echo "  \"update\": \"${UPDATE_SECRET}\","
  echo "  \"notify\": \"${NOTIFY_SECRET}\","
  echo "  \"anchor\": $(echo "$ANCHOR_DATA" | jq -c .)"
  echo "}"

}


# ### main

trap cleanup EXIT
if test "$1" = "--id" -a "$2" != ""; then
  ID="$2"
  shift 2
else
  echo "Error: missing --id name"
  usage
  exit 1
fi
generate_keys
