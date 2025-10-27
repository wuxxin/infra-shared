#!/usr/bin/env bash
set -eo pipefail
# set -x

this_dir=$(dirname "$(readlink -e "$0")")
this_dir_short=$(basename "${this_dir}")
shared_dir=$(readlink -f "${this_dir}/..")
shared_dir_short=$(basename "${shared_dir}")
project_dir="${this_dir}/../.."

usage() {
    cat - <<EOF
Usage: $(basename "$0") [--project-dir dirname] [--name-library dirname] --yes

Creates directories and minimal files needed for a new project.

--yes                   Confirms the execution of the script

--project-dir dirname   Specify the project directory. If provided,
    it's treated as relative to the current working directory
    If not specified, defaults to '../../'
    (relative to the script's parent directory: ${this_dir}/../..)

--name-library dirname  If specified, this dirname will be used instead the
  current one for the references to the shared infrastructure dir, eg. "infra"

EOF
}

if test "$1" = "--project-dir" -a "$2" != ""; then
    project_dir="$2"
    shift 2
fi
if test "$1" = "--name-library" -a "$2" != ""; then
    shared_dir_short="$2"
    shift 2
fi
if test "$1" != "--yes"; then
    echo "Error: The --yes flag is mandatory." >&2
    usage
    exit 1
fi

# Convert project_dir to an absolute path.
#   If it was provided as an argument, it's relative to CWD
#   If default was used, it's relative to the script's parent dir
project_dir=$(readlink -f "${project_dir}")
project_name=$(basename "${project_dir}")

create_ifnotexist() { #1 filename relative to project_dir
    fname="${project_dir}/$1"
    if test ! -e "$fname"; then
        echo "Writing file: $fname"
        cat - >"$fname"
    else
        echo "Warning: not touching existing file $fname"
        # discard stdin if we're not using it
        cat - >/dev/null
    fi
}

# test for .git or create and initialize project_dir
if [ -d "${project_dir}" ]; then
    if [ ! -d "${project_dir}/.git" ]; then
        echo "Error: Project directory ${project_dir} exists but is not a Git repository." >&2
        echo "Please initialize it as a Git repository or choose a different directory." >&2
        exit 1
    fi
else
    echo "Project directory ${project_dir} does not exist. \nCreating and initializing as a Git repository..."
    mkdir -p "${project_dir}"
    if ! git init "${project_dir}"; then
        echo "Error: Failed to initialize Git repository in ${project_dir}." >&2
        rmdir "${project_dir}" 2>/dev/null || echo "Warning: Could not remove directory ${project_dir} after failed git init." >&2
        exit 1
    fi
fi

# create subdirs and add .gitkeep file
for d in docs state target; do
    mkdir -p "${project_dir}/${d}"
    create_ifnotexist "${d}/.gitkeep" </dev/null
done

# copy and template: Makefile, pyproject.toml
for f in Makefile pyproject.toml; do
    # replace hardcoded instances of infra/ and project_name for custom naming
    cat "${shared_dir}/examples/skeleton/${f}" |
        sed -r "s#infra/#${shared_dir_short}/#g" |
        sed -r "s#project_name#${project_name}#g" |
        create_ifnotexist "${f}"
done

# create an empty authorized_keys for appending to it later
create_ifnotexist authorized_keys </dev/null

# symlink README.md to docs
# Check if docs/README.md already exists to avoid error if it's a regular file or different symlink
if [ ! -e "${project_dir}/docs/README.md" ]; then
    ln -s ../README.md "${project_dir}/docs/README.md"
else
    echo "Warning: ${project_dir}/docs/README.md already exists. Skipping symlink creation."
fi

create_ifnotexist README.md <<EOF
# ${project_name}

Software Defined Git Operated Infrastructure

EOF

create_ifnotexist __main__.py <<EOF
"""A Python Pulumi program"""


import ${shared_dir_short}.authority

EOF

create_ifnotexist Pulumi.yaml <<EOF
name: ${project_name}
runtime:
  name: python
  options:
    virtualenv: .venv
description: ${project_name} pulumi infrastructure

EOF

create_ifnotexist config-template.yaml <<EOF
config:
  libvirt:uri: qemu:///system
  ${project_name}:locale:
    lang: en_US.UTF-8
    keymap: us
    timezone: UTC
    country_code: UN

EOF

create_ifnotexist .gitignore <<EOF
# python virtualenv
.venv

# directory for temporary files
build/tmp

# saltstack state files
build/salt

# mkdocs generated documentation files
build/docs

# pulumi state for stacks "*sim"
state/pulumi/.pulumi/backups/*sim
state/pulumi/.pulumi/history/*sim
state/pulumi/.pulumi/locks/*sim
state/pulumi/.pulumi/stacks/*sim.json*

# pulumi config for stacks "*sim"
Pulumi.*sim.yaml

# exported infrastructure states files for stacks "*sim"
state/files/*sim

# interactive python checkpoints
.ipynb_checkpoints

# python package info
${project_name}.egg-info

# compiled python
*.pyc
__pycache__

# editor artifacts
.zed

EOF

create_ifnotexist mkdocs.yml <<EOF
site_name: ${project_name} Infrastructure

theme:
  name: material

plugins:
  - search
  - include-markdown

markdown_extensions:
  - smarty
  - toc:
      permalink: "#"
  - pymdownx.magiclink
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format

nav:
  - README.md

EOF

echo "Skeleton for project ${project_name} created in ${project_dir}"
