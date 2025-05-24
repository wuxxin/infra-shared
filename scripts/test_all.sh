#!/usr/bin/env bash
set -eo pipefail

THIS_DIR=$(dirname "$(readlink -e "$0")")
PROJECT_ROOT=$(readlink -f "${this_dir}/..")
PROJECT_NAME=$(basename "${PROJECT_ROOT}")

echo "create workdir"
WORKDIR_PATH="$(mktemp -d /tmp/worktemp_${PROJECT_NAME}_XXXXXX)"
if [ -z "${WORKDIR_PATH}" ] || [ ! -d "${WORKDIR_PATH}" ]; then
    echo "Error: Could not create temporary directory." >&2
    exit 1
fi
trap 'echo "Cleaning up ${WORKDIR_PATH}" >&2; if test -d "${WORKDIR_PATH}"; then rm -r "${WORKDIR_PATH}"; fi' EXIT

echo "git init"
cd "${WORKDIR_PATH}"
git init
"${PROJECT_ROOT}/scripts/create_skeleton.sh" --project-dir . --yes

echo "symlink this subproject into created tree"
ln -s "${PROJECT_ROOT}" "${PROJECT_NAME}"

echo "export CONTAINER_CMD to use sudo docker"
export CONTAINER_CMD="sudo docker"

echo "Running make provision-client..."
make provision-client

echo "Running make build-env via ${PROJECT_NAME}/scripts/provision_shell.sh..."
"${PROJECT_NAME}/scripts/provision_shell.sh" "make build-env"

echo "Running make sim-up via ${PROJECT_NAME}/scripts/provision_shell.sh..."
"${PROJECT_NAME}/scripts/provision_shell.sh" "make sim-up"

echo "Test operations completed in ${WORKDIR_PATH}."
