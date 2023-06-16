# infra-shared
## Software Defined Git Operated Infrastructure

Reusables of a learning project by rewriting parts of my home infrastructure

as a **pulumi** and **core-os** based **gitops** project in **python**.

- Inspired and impressed by https://github.com/deuill/coreos-home-server
- See https://github.com/wuxxin/example_infra for usage in an example project

### Quick start

create a base project, lock and install build requirements,
install and configure a simulation of the targets

```sh
mkdir -p example; cd example; git init
git submodule add https://github.com/wuxxin/infra-shared.git infra
infra/create_skeleton.sh --yes
make sim-up
```

**Congratulations!**

You have just created two TLS Certificates and an SSH Keypair in a very fancy way!

To see what else you can do with it, continue reading or look at:
- look at https://github.com/wuxxin/example_infra for usage in an example project
- also see the [jupter notebooks](https://github.com/wuxxin/example_infra/notebooks) there for interactive pulumi, mqtt and homeassistant examples


### Features

Pulumi Components for

- Fedora-CoreOS Linux - updating, minimal, monolithic, container-focused operating system
    - Setup, Bootstrap and Reconfiguration of CoreOS with Jinja templated butane files
    - Reconfiguration: `coreos-update-config*`
        - Fast (~4s) reconfiguration based on `butane2salt.jinja` translation
    - **Single Container**: `podman-systemd.unit`
        - `containers*` - run systemd container units using podman-quadlet
    - **Compose Container**: `compose.yml`
        - `compose*` - run multi-container applications defined using a compose file
    - **nSpawn OS-Container**: `systemd-nspawn`
        - `nspawn*` - run an linux OS (build by mkosi) in a light-weight container

- `authority.py` - TLS Certificate-Authority, functions for TLS Certificates and SSH-Provision
- `tools.py` - SSH copy/deploy/execute functions, Jinja Templating, local and remote Salt-Call
- `build.py` - build Embedded-OS Images and IOT Images
    - **Openwrt** Linux - Network Device Distribution for Router and other network devices
    - **Homeassistant** OS - Linux based home automation Control Bridge (Zigbee,BT,Wifi)
    - **Esphome** - yaml configured Sensor/Actor for ESP32 Devices on Arduino or ESP-IDF
- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN


Provision can be run on **Arch** Linux, **Manjaro** Linux or as **Container Image**.

**Need to know** technologies (to write Deployment and Docs):
- Basic Knowledge of Python, Yaml, Jinja, Systemd Service, Containerfile, Markdown

**Advanced functionality** available with knowledge of:
- Pulumi, Butane, more Systemd, Fcos, Saltstack, Podman, compose.yml, makefile, Pipfile, libvirt, Bash, Mkdocs, Mermaid, Jupyter Notebooks

### Usage


#### List available Makefile targets/commands

```sh
make
```

#### Bootstrap skeleton files to a new repo

- from current directory, eg. pwd=~/code

```sh
project_name=example
base_dir=$(pwd)
project_dir=${base_dir}/${project_name}
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
        - README.md, \_\_main\_\_.py, Pulumi.yaml, Makefile, Pipfile
        - config-template.yaml, .gitignore, mkdocs.yml, empty authorized_keys

#### Install build requirements

+ on arch or manjaro linux

```sh
make install-requirements
```

+ on other linux, use a build container

```sh
# Either: build container using sudo podman build
make provision-container

# Or: build container using any other container tool
# - replace "docker" with your container build call
cd infra/Containerfile/provision-client && docker build -t provision-client:latest $(pwd)

# add a provision-client() function to running shell
# - replace "sudo podman" to match your local container software
source /dev/stdin <<'EOF'
provision-client() {
  test "${1}" = "" && set -- "/usr/bin/bash" "${@:1}"; \
  sudo podman run -it --rm \
  --user="$(id -u):$(id -g)" --network=host \
  -v "/etc/passwd:/etc/passwd:ro" -v "/etc/group:/etc/group:ro" \
  -v "$HOME:$HOME" -v "$(pwd):$(pwd)" -v "$XDG_RUNTIME_DIR:$XDG_RUNTIME_DIR" \
  -e "HOME=$HOME" -e "PWD=$(pwd)" -e "LANG=$LANG" -e "TERM=$TERM" -e "USER=$USER" \
  -e "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
  -w "$(pwd)" \
  localhost/provision-client \
  "${@:1}"
}
EOF

# call provision client (defaults to /usr/bin/bash interactive shell)
provision-client

# add `provision-client() {...}` to .bashrc to have it available every time.
```


#### Build documentation

```sh
make docs
```

#### Create/build/install simulation target
```sh
make sim-up
```

#### Show/use root and provision cert
```sh
make sim__ args="stack output ca_factory --json" | \
    jq ".root_cert_pem" -r | openssl x509 -in - -noout -text
make sim__ args="stack output ca_factory --json" | \
    jq ".provision_cert_pem" -r  | openssl x509 -in - -noout -text
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
pipenv run ipython
```

#### Sim stack: destroy, cleanup, re/create
```sh
make sim-clean
make sim-create
```

#### Manual execution of the openwrt image build by calling a function
```sh
pipenv run infra/tools.py sim infra.build build_openwrt
# show recorded image build salt-call stdout log output
make sim-show | jq .build_openwrt.result.stdout -r
```

#### test if changes would compute before applying
```sh
make sim__ args="preview --suppress-outputs"
make sim-up
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
make prod__ args=preview
make prod__ args=up
```

### Architecture

#### Objectives

- **avoid legacy** technologies, build a clear **chain of trust**, support **encrypted storage** at rest
    - use **ssh keys** as root of trust for pulumi **stack secret** using **age**
    - store **secrets in the repository** using pulumi config secrets
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
- create **disposable/immutable-ish** infrastructure, aim for **structural isolation** and reusability
- treat **state as code**
    - favor **state reconcilation**- and other highlevel- tools
    - have the **complete encrypted state** in the **git repository** as **single source of truth**
- have a **big/full featured provision client** as the center of operation
    - target one **provision os** and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable local **simulation environment** with **fast reconfiguration** turnaround
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **jupyter notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**

#### Technologies

- `pulumi` - imperativ infrastructure delaration using python
- `fcos` - Fedora-CoreOS, minimal OS with `clevis` (sss,tang,tpm) storage unlock
- `butane` - create fcos `ignition` configs using `jinja` enhanced butane yaml
- `systemd` - service, socker, path, timer, nspawn machine container
- `podman` - build Container images, run Container using quadlet systemd container
- `saltstack`
    - local embedded/iot build environments, local user services
    - remote fcos config update using butane to saltstack translation and execution
- `mkdocs` - documentation using markdown and mermaid
- `libvirt` - simulation of machines using the virtualization api supporting qemu and kvm
- `tang` - server used for getting a key shard for unattended encrypted storage unlock on boot
- `mkosi` - build nspawn OS container images
- `age` - ssh keys based encryption of production files and pulumi master password
- `pipenv` - virtualenv management using Pipfile and Pipfile.lock

### License

```
All code in this repository is covered by the terms of the Apache 2.0 License,
the full text of which can be found in the LICENSE file.
```
