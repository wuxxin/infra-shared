#!/usr/bin/env bash
set -eo pipefail
# set -x

usage() {
  cat <<EOF
Usage:  <json-from-stdin> | $0 --yes | <json-to-stdout>

use vault as a commandline pipe (non recommended usage),
  input configuration JSON from STDIN,
  output a root authority and two provision authority certificates as JSON to STDOUT.

because of vaults excellent pki support, this includes support for permitted_dns_domains.

input
  - must contain the following json dictionary, with some defaults
  - may contain "ca_permitted_domains", defaults to ""
  - may contain "ca_max_path_length", defaults to 3 if not present
  - may contain "ca_validity_period_hours", defaults to 70080 (8 Years) if not present
  - additional entries are ignored

STDIN:JSON
{
  "ca_name": "",
  "ca_org": "",
  "ca_unit": "",
  "ca_locality": "",
  "ca_country": "",
  "ca_permitted_domains": "",
  "ca_dns_names": "",
  "ca_provision_name": "",
  "ca_provision_unit": "",
  "ca_provision_dns_names": "",
  "ca_alt_provision_name": "",
  "ca_alt_provision_unit": "",
  "ca_alt_provision_dns_names": "",
  "ca_validity_period_hours": "${default_ca_validity_period}",
  "ca_max_path_length": "${default_ca_max_path_length}"
}

output
  - contains the pem formatted key,request,cert files in a json dictionary

STDOUT:JSON
{
  "ca_root_key_pem": "",
  "ca_root_cert_pem": "",
  "ca_provision_key_pem": "",
  "ca_provision_request_pem": "",
  "ca_provision_cert_pem": "",
  "ca_alt_provision_key_pem": "",
  "ca_alt_provision_request_pem": "",
  "ca_alt_provision_cert_pem": ""
}

EOF
}

waitfor_port() { # $1=hostname $2=port [$3=maxretries]
  local retries maxretries retry hostname port
  retries=0
  maxretries=5
  retry=true
  hostname="$1"
  port="$2"
  if test "$3" != ""; then maxretries="$3"; fi

  while "$retry"; do
    ((retries += 1))
    if test "$retries" -ge "$maxretries"; then return; fi
    nc -z -w 2 "$hostname" "$port" &>/dev/null && err=$? || err=$?
    if test "$err" -eq "0"; then retry=false; fi
    sleep 1
  done
}

#
#
# main

default_ca_validity_period=$((24 * 365 * 8))
default_ca_max_path_length=3

if test "$1" != "--yes"; then
  usage
  exit 1
fi

# read config from stdin
config_json="$(cat -)"
# printf "%s" "$config_json" >/tmp/vault_input.json

ca_name=$(echo "$config_json" | jq ".ca_name" -r -e)
ca_org=$(echo "$config_json" | jq ".ca_org" -r -e)
ca_unit=$(echo "$config_json" | jq ".ca_unit" -r -e)
ca_locality=$(echo "$config_json" | jq ".ca_locality" -r -e)
ca_country=$(echo "$config_json" | jq ".ca_country" -r -e)
ca_dns_names=$(echo "$config_json" | jq ".ca_dns_names" -r -e)
ca_provision_name=$(echo "$config_json" | jq ".ca_provision_name" -r -e)
ca_provision_unit=$(echo "$config_json" | jq ".ca_provision_unit" -r -e)
ca_provision_dns_names=$(echo "$config_json" | jq ".ca_provision_dns_names" -r -e)
ca_alt_provision_name=$(echo "$config_json" | jq ".ca_alt_provision_name" -r -e)
ca_alt_provision_unit=$(echo "$config_json" | jq ".ca_alt_provision_unit" -r -e)
ca_alt_provision_dns_names=$(echo "$config_json" | jq ".ca_alt_provision_dns_names" -r -e)

# make permitted_dns_domains an optional parameter to vault
optional_ca_permitted_domains=""
ca_permitted_domains=$(echo "$config_json" | jq ".ca_permitted_domains" -r)
if test "$ca_permitted_domains" != "null"; then
  optional_ca_permitted_domains="permitted_dns_domains=${ca_permitted_domains}"
fi

# substract one day from provision cert, so it expires one day earlier than root ca
ca_validity_period="$(echo "$config_json" |
  jq ".ca_validity_period_hours // ${default_ca_validity_period}" -r)"
ca_validity_period_hours="${ca_validity_period}h"
ca_provision_validity_period_hours="$((ca_validity_period - 24))h"

# keep minimum max_path_length at 2, for provision ca support
ca_max_path_length=$(echo "$config_json" |
  jq ".ca_max_path_length // ${default_ca_max_path_length}" -r)
if test "$ca_max_path_length" = "1"; then ca_max_path_length="2"; fi

# make a in memory vault server, with random token and random port
export VAULT_TOKEN="$(openssl rand -hex 16)"
export VAULT_ADDR="http://127.0.1.1:58$(shuf -i "100-254" -n 1)"
vault_host_port="${VAULT_ADDR#http://}"
vault_host=${vault_host_port%%:*}
vault_port=${vault_host_port##*:}

vault server -dev -dev-no-store-token \
  -dev-root-token-id="$VAULT_TOKEN" \
  -dev-listen-address="${VAULT_ADDR#http://}" &>/dev/null &
vault_pid=$!
trap 'if test "$vault_pid" != ""; then kill -1 $vault_pid &>/dev/null || true; kill -9 $vault_pid &>/dev/null || true; exit 9; fi; exit 0' EXIT

waitfor_port "$vault_host" "$vault_port"
vault secrets enable pki &>/dev/null
max_lease_ttl="87600h" # = 10 years in hours
vault secrets tune "-max-lease-ttl=${max_lease_ttl}" pki &>/dev/null

ca_root_raw="$(
  vault write -format json pki/root/generate/exported \
    ttl=${ca_validity_period_hours} \
    key_type="ec" \
    key_bits="384" \
    key_usage="CRL,CertSign,DigitalSignature" \
    max_path_length="${ca_max_path_length}" \
    exclude_cn_from_sans=true \
    issuer_name="${ca_name}" \
    common_name="${ca_name}" \
    country="${ca_country}" \
    locality="${ca_locality}" \
    organization="${ca_org}" \
    ou="${ca_unit}" \
    alt_names="${ca_dns_names}" \
    "${optional_ca_permitted_domains}"
)"
# echo "$ca_root_raw" >/tmp/ca_root_raw.txt

prov_req_raw="$(
  vault write -format json pki/intermediate/generate/exported \
    key_type="ec" \
    key_bits="384" \
    key_usage="CRL,CertSign,DigitalSignature" \
    exclude_cn_from_sans=true \
    common_name="${ca_provision_name}" \
    country="${ca_country}" \
    locality="${ca_locality}" \
    organization="${ca_org}" \
    ou="${ca_provision_unit}" \
    alt_names="${ca_provision_dns_names}"
)"
ca_provision_request_pem=$(echo "$prov_req_raw" | jq ".data.csr" -r)
# echo "$prov_req_raw" >prov_req_raw.txt

alt_prov_req_raw="$(
  vault write -format json pki/intermediate/generate/exported \
    key_type="ec" \
    key_bits="384" \
    key_usage="CRL,CertSign,DigitalSignature" \
    exclude_cn_from_sans=true \
    common_name="${ca_alt_provision_name}" \
    country="${ca_country}" \
    locality="${ca_locality}" \
    organization="${ca_org}" \
    ou="${ca_alt_provision_unit}" \
    alt_names="${ca_alt_provision_dns_names}"
)"
ca_alt_provision_request_pem=$(echo "$alt_prov_req_raw" | jq ".data.csr" -r)
# echo "$alt_prov_req_raw" >/tmp/alt_prov_req_raw.txt

prov_cert_raw="$(
  echo "$ca_provision_request_pem" |
    vault write -format json pki/root/sign-intermediate \
      csr=- \
      ttl=${ca_provision_validity_period_hours} \
      max_path_length=$((ca_max_path_length - 1)) \
      exclude_cn_from_sans=true \
      use_csr_values=true
)"
# echo "$prov_cert_raw" >/tmp/prov_cert_raw.txt

alt_prov_cert_raw="$(
  echo "$ca_alt_provision_request_pem" |
    vault write -format json pki/root/sign-intermediate \
      csr=- \
      ttl=${ca_provision_validity_period_hours} \
      max_path_length=$((ca_max_path_length - 1)) \
      exclude_cn_from_sans=true \
      use_csr_values=true
)"
# echo "$alt_prov_cert_raw" >/tmp/alt_prov_cert_raw.txt

ca_root_json=$(echo "$ca_root_raw" |
  jq "{ca_root_key_pem: .data.private_key, ca_root_cert_pem:.data.certificate}")
ca_prov_req_json=$(echo "$prov_req_raw" |
  jq "{ca_provision_key_pem: .data.private_key, ca_provision_request_pem: .data.csr}")
ca_alt_prov_req_json=$(echo "$alt_prov_req_raw" |
  jq "{ca_alt_provision_key_pem: .data.private_key, ca_alt_provision_request_pem: .data.csr}")
ca_prov_cert_json=$(echo "$prov_cert_raw" |
  jq "{ca_provision_cert_pem: .data.certificate}")
ca_alt_prov_cert_json=$(echo "$alt_prov_cert_raw" |
  jq "{ca_alt_provision_cert_pem: .data.certificate}")

vault_result=$(echo "$ca_root_json
$ca_prov_req_json
$ca_alt_prov_req_json
$ca_prov_cert_json
$ca_alt_prov_cert_json" | jq -s 'add')
# printf "%s" "$vault_result" >/tmp/vault_result.json
echo "$vault_result"

kill -1 $vault_pid &>/dev/null || true
sleep 1
kill -9 $vault_pid &>/dev/null || true
vault_pid=""
