#!/usr/bin#/env bash
set -eo pipefail

usage() {
    cat <<EOF
Usage: $(basename $0) project_name resource_name stack_name base_dir root_dir tmp_dir sls_dir pillar_dir
EOF
    exit 1
}

if test "$8" = ""; then usage; fi

project_name="$1"
resource_name="$2"
stack_name="$3"
base_dir="$4"
root_dir="$5"
tmp_dir="$6"
sls_dir="$7"
pillar_dir="$8"

cat >${root_dir}/minion <<EOF
id: ${resource_name}
local: True
log_level_logfile: info
file_client: local
fileserver_backend:
- roots
file_roots:
  base:
  - ${sls_dir}
pillar_roots:
  base:
  - ${pillar_dir}
grains:
  project_name: ${project_name}
  resource_name: ${resource_name}
  stack_name: ${stack_name}
  base_dir: ${base_dir}
  root_dir: ${root_dir}
  tmp_dir: ${tmp_dir}
  sls_dir: ${sls_dir}
  pillar_dir: ${pillar_dir}
root_dir: ${root_dir}
conf_file: ${root_dir}/minion
pki_dir: ${root_dir}/etc/salt/pki/minion
pidfile: ${root_dir}/var/run/salt-minion.pid
sock_dir: ${root_dir}/var/run/salt/minion
cachedir: ${root_dir}/var/cache/salt/minion
extension_modules: ${root_dir}/var/cache/salt/minion/extmods
log_file: ${root_dir}/var/log/salt/minion

EOF
