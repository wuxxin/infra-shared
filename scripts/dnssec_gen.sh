#!/usr/bin/env bash
set -eo pipefail

TEMP_DIR_BASE="/run/user/$(id -u)"
ZONE=""

usage() {
  cat <<EOF

Usage: $0 --zone name

Generates DNSSEC KSK private and public key (Anchor Data) and outputs them as JSON.

  Ensures that created temporary files are in ram temp and deleted afterwards.
EOF
}

cleanup() {
  # $? contains the exit code of the last command
  local exit_code=$?

  if test -d "${TEMP_DIR}"; then
    # Only print the config file on error (non-zero exit code)
    if test "$exit_code" -ne 0 && test -e "${TEMP_DIR}/knot.conf"; then
      echo "An error occurred. Knot configuration:" >&2 # Output to stderr
      cat "${TEMP_DIR}/knot.conf" >&2
    fi
    rm -rf "${TEMP_DIR}"
  fi
  exit "$exit_code"
}

generate_keys() {
  TEMP_DIR=$(mktemp -d -p "${TEMP_DIR_BASE}" "dnssec-keys-XXXXXXXXXX")
  if [[ ! -d "$TEMP_DIR" ]]; then
    echo "Error: Failed to create temporary directory" >&2
    exit 1
  fi

  cat >"${TEMP_DIR}/knot.conf" <<EOF
server:
  # No server settings needed for key generation
database:
  storage: ${TEMP_DIR}
# Define a minimal zone
zone:
  - domain: ${ZONE}
    storage: ${TEMP_DIR}
    journal-content: none
EOF

  # Generate DNSSEC keys and capture Key IDs
  keymgr -c "${TEMP_DIR}/knot.conf" "${ZONE}." generate \
    algorithm=ecdsap256sha256 ksk=true >/dev/null
  KSK_ID=$(keymgr -c "${TEMP_DIR}/knot.conf" "${ZONE}." list -j | jq -r ".[0].id")
  # Generate trust anchor (KSK public key)
  ANCHOR_DATA=$(keymgr -c "${TEMP_DIR}/knot.conf" "${ZONE}." dnskey "$KSK_ID")
  # get private key
  KSK_DATA=$(cat ${TEMP_DIR}/keys/keys/${KSK_ID}.pem)
  # find $TEMP_DIR
  # echo "KSK_ID: $KSK_ID"
  # DUMP=$(mdb_dump -a ${TEMP_DIR}/keys)

  # return JSON output
  jq -n \
    --arg ksk "$KSK_DATA" \
    --arg anchor "$ANCHOR_DATA" \
    '{
      ksk_key: $ksk,
      ksk_anchor: $anchor
    }'
}

# ### main

trap cleanup EXIT
if test "$1" = "--zone" -a "$2" != ""; then
  ZONE="$2"
  shift 2
else
  echo "Error: missing --zone name"
  usage
  exit 1
fi
generate_keys
