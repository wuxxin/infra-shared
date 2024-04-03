#!/usr/bin/env bash
set -eo pipefail
# set -x  

test "${1}" = "" && set -- "/usr/bin/bash" "${@:1}"; \
podman run -it --rm \
    --user="$(id -u):$(id -g)" --network=host \
    -v "/etc/passwd:/etc/passwd:ro" -v "/etc/group:/etc/group:ro" \
    -v "$HOME:$HOME" -v "$(pwd):$(pwd)" -v "$XDG_RUNTIME_DIR:$XDG_RUNTIME_DIR" \
    -e "HOME=$HOME" -e "PWD=$(pwd)" -e "LANG=$LANG" -e "TERM=$TERM" -e "USER=$USER" \
    -e "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
    -w "$(pwd)" \
    localhost/provision-client \
    "${@:1}"
