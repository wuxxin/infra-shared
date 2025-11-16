#!/usr/bin/env bash
set -eo pipefail
# set -x

# Default to /usr/bin/bash if no command is provided
test "${1}" = "" && set -- "/usr/bin/bash" "${@:1}"

_UID=$(id -u)
_GID=$(id -g)
_PWD=$(pwd)
CONTAINER_CMD="${CONTAINER_CMD:-podman}"

# Warn about missing subuid/gid mappings
if [[ -f /etc/subuid && -f /etc/subgid ]] && grep -q "^$(id -un):" /etc/subuid && grep -q "^$(id -gn):" /etc/subgid; then
    true
else
    echo "Warning: /etc/subuid or /etc/subgid mappings for user $(id -un) look missing. --userns=keep-id might not work as expected." >&2
fi

# Run the container
"$CONTAINER_CMD" run -it --rm \
    --user="$_UID:$_GID" \
    --userns=keep-id \
    --network=host \
    -v "provision-home:$HOME" \
    -v "/etc/passwd:/etc/passwd:ro" \
    -v "/etc/group:/etc/group:ro" \
    -v "$(pwd):$(pwd):Z" \
    -v "$XDG_RUNTIME_DIR:$XDG_RUNTIME_DIR:Z" \
    -e "HOME=$HOME" \
    -e "PWD=$(pwd)" \
    -e "LANG=${LANG:-en_US.UTF-8}" \
    -e "TERM=${TERM:-xterm}" \
    -e "USER=$USER" \
    -e "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
    -w "$(pwd)" \
    localhost/provision-client \
    "${@:1}"
