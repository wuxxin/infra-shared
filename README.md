# infra-shared

## Software Defined Git Operated Infrastructure

Reusables of a learning project by rewriting parts of my home infrastructure as

a **Pulumi** (Terraform-ish) and **Fedora Coreos** based **Gitops** Project in **Python**.

- See [safe](examples/safe) for usage in an example project

### Quick start

create a base project, lock and install build requirements,
install and configure a simulation of the targets

```sh
mkdir -p example; cd example; git init
git submodule add https://github.com/wuxxin/infra-shared.git infra
infra/scripts/create_skeleton.sh --yes
make sim-up
```

**Congratulations!**

You have just created two TLS Certificates and an SSH Keypair in a very fancy way!

See the [examples](examples/) for code of what else can be done with it

### Features

- **Appliance** based on **Fedora-CoreOS Linux** - updating, minimal, monolithic, container-focused operating system
    - **Setup**: Bootstrap and Reconfiguration of CoreOS with **Jinja templated butane** files
    - **Reconfiguration**: `update-system-config*`
        - Fast (~4s) reconfiguration using saltstack and butane to salt translation
    - **Single Container**: `podman-systemd.unit`
        - `container*` - run systemd container units using podman-quadlet
    - **Compose Container**: `compose.yml`
        - `compose*` - run multi-container applications defined using a compose file
    - **nSpawn OS-Container**: `systemd-nspawn`
        - `nspawn*` - run any linux OS in a light-weight system container
    - **tls/http/web FrontEnd**: `traefik`
        - using container, compose and nspawn labels for dynamic configuration
    - **DNS Resolver**: `unbound`
        - using container for local DNSSEC capable recursive DNS-Resolver
- **TLS Certificate-Authority**, TLS Certificates and **SSH**-Certificates
- **SSH** copy/deploy/execute functions, local and remote **Salt-Call**
- **serve** configuration **HTTPS** payloads, request a port forwarding
- **write** image to **removable storage** specified by serial_number
- build Embedded-OS Images and IOT Images
    - **Raspberry PI Extras** - Eeprom, U-Boot and UEFI bios files
    - **Openwrt Linux** - Network Device Distribution for Router and other network devices

### Technologies

**Need to know** technologies (to write Deployment and Docs):

- Basic Knowledge of `Python, Yaml, Jinja, Systemd Service, Containerfile, Markdown`

**Advanced functionality** available with knowledge of:

- Pulumi, Butane, more Systemd, Fcos, Saltstack, Podman, compose.yml, makefile, pyproject.toml, libvirt, Bash, Mkdocs, Mermaid, Jupyter or Marimo Notebooks

Provision can be run on **Arch** Linux, Manjaro Linux or as **Container Image**.

#### Tools used

- `pulumi` - imperativ infrastructure delaration using python
- `fcos` - Fedora-CoreOS, minimal OS with `clevis` (sss,tang,tpm) storage unlock
- `butane` - create fcos `ignition` configs using `jinja` enhanced butane yaml
- `systemd` - service, socker, path, timer, nspawn machine container
- `podman` - build Container and NSpawn images, run Container using quadlet systemd container
- `saltstack`
    - local build environments and local services
    - remote fcos config update using butane to saltstack translation and execution
- `mkdocs` - documentation using markdown and mermaid
- `libvirt` - simulation of machines using the virtualization api supporting qemu and kvm
- `tang` - server used for getting a key shard for unattended encrypted storage unlock on boot
- `age` - ssh keys based encryption of production files and pulumi master password
- `uv`- virtualenv management using pyproject.toml and uv.lock

### Usage

#### List available Makefile targets/commands

```sh
make
```

#### Bootstrap skeleton files to a new repo

- from current directory, eg. pwd=~/code

```sh
project_name=example
current_dir=$(pwd)
project_dir=${current_dir}/${project_name}
mkdir -p ${project_dir}
cd ${project_dir}
git init
git submodule add https://github.com/wuxxin/infra-shared.git infra
infra/create_skeleton.sh --yes
```

- `create_skeleton.sh` creates default dirs and files in the project_dir
    - use `cat infra/create_skeleton.sh` to inspect script before running it
    - directories created:
        - _docs_, _state_, _target_ with an empty _.gitkeep_ file inside
    - files created:
        - README.md, \_\_main\_\_.py, Pulumi.yaml, Makefile, pyproject.toml
        - config-template.yaml, .gitignore, mkdocs.yml, empty authorized_keys

#### Install build requirements

- on arch linux or manjaro linux

```sh
make install-requirements
```

- on other linux, use a provision container.

This needs podman or docker already installed on host.

For the simulation environment with libvirt the host system must also have a configured libvirt.

```sh
# Either: build container using `sudo podman build`
make provision-client

# Or: build container using any other container tool
# - replace "docker" with the preferred container build call
cd infra/Containerfile/provision-client && \
    docker build -t provision-client:latest $(pwd)

# call provision shell(defaults to /usr/bin/bash interactive shell)
# defaults to podman, but can be overriden with DOCKER_CMD=executable
DOCKER_CMD=docker infra/scripts/provision_shell.sh
# use exit to return to base shell
```

#### Build documentation

```sh
make docs
# build infra-shared documentation
make docs-infra
```

#### Create/build/install simulation target

```sh
make sim-up
```

#### Show/use root and provision cert

```sh
make sim-show args="ca_factory" | jq ".root_cert_pem" -r | \
    openssl x509 -in /dev/stdin -noout -text
make sim-show args="ca_factory" | jq ".provision_cert_pem" -r | \
    openssl x509 -in /dev/stdin -noout -text
```

#### Manual pulumi invocation

```sh
export PULUMI_SKIP_UPDATE_CHECK=1
export PULUMI_CONFIG_PASSPHRASE=sim

pulumi stack select sim
pulumi about
```

#### Execute in provision python environment

```sh
uv run ipython
```

#### Sim stack: destroy, cleanup, re/create

```sh
make sim-clean
# in case something happend while destroying sim stack
make sim__ args="stack rm --force"; rm Pulumi.sim.yaml
# recreate stack
make sim-create
```

#### test if changes would compute before applying

```sh
make sim-preview
# if list of changes looks good, apply them
make sim-up

```

#### cancel an currently running/stuck pulumi update

```sh
# "error: the stack is currently locked by 1 lock(s)."
# "Either wait for the other process(es) to end or delete the lock file with `pulumi cancel`."
make sim__ args="cancel"
```

#### show resource output as json

```sh
make sim-show
```

#### show resource output key list as yaml

```sh
make sim-list
```

#### show resource output data as colorized formatted json or yaml

```sh
# use highlight and less
make sim-show | highlight --syntax json -O ansi | less
# use bat for integrated highlight plus pager
make sim-show | bat -l json
```

### Production

#### Add SSH Keys of GitOps Developer

```sh
# eg. add the own ssh public key in project_dir/authorized_keys
cat ~/.ssh/id_rsa.pub >> authorized_keys
```

#### Create stack

```sh
make prod-create
make prod__ args="preview --suppress-outputs"
make prod__ args=up
```

### Credits

- Inspired and impressed by [deuill/coreos-home-server](https://github.com/deuill/coreos-home-server)

### License

```text
All code in this repository is covered by the terms of the Apache 2.0 License,
the full text of which can be found in the LICENSE file.
```
