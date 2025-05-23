#!/usr/bin/env bash
set -eo pipefail
# set -x

this_dir=$(dirname "$(readlink -e "$0")")
this_dir_short=$(basename "${this_dir}")

shared_dir=$(readlink -f ${this_dir}/..)
shared_dir_short=$(basename "${shared_dir}")

project_dir=$(readlink -f ${this_dir}/../..)
project_name=$(basename "${project_dir}")

usage() {
  cat - <<EOF
$(basename $0) --yes

creates directories relative to this subproject parent dir (../../)
  and creates and minimal files needed for a project

EOF
}

create_ifnotexist() { #1 filename relative to ./../
  fname="${project_dir}/$1"
  if test ! -e "$fname"; then
    echo "Writing file: $fname"
    cat - >"$fname"
  else
    echo "Warning: not touching existing file $fname"
    cat - >/dev/null
  fi
}

if test "$1" != "--yes"; then
  usage
  exit 1
fi

# create subdirs and add .gitkeep file
for d in docs state target; do
  mkdir -p ${project_dir}/${d}
  create_ifnotexist ${d}/.gitkeep </dev/null
done

# copy and template: Makefile, pyproject.toml
for f in Makefile pyproject.toml; do
  # replace hardcoded instances of infra/ and project_name for custom naming
  cat ${shared_dir}/examples/skeleton/${f} |
    sed -r "s#infra/#${shared_dir_short}/#g" |
    sed -r "s#project_name#${project_name}#g" |
    create_ifnotexist ${f}
done

# create an empty authorized_keys for appending to it later
create_ifnotexist authorized_keys </dev/null

# symlink README.md to docs
ln -s ../README.md ${project_dir}/docs/README.md

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
state/tmp

# saltstack state files
state/salt

# mkdocs generated documentation files
state/docs

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
.vscode
.zed

EOF

create_ifnotexist mkdocs.yml <<EOF
site_name: ${project_name} Infrastructure

theme:
  name: material

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
