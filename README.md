# infra-shared

Software Defined Git Operated Infrastructure As Code.


reusables of a **learning project** by rewriting parts of my home infrastructure

as a **pulumi and core-os** based **gitops** project in **python**.


Inspired and impressed by https://github.com/deuill/coreos-home-server

See https://github.com/wuxxin/example_infra for usage in an example project

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


### Architecture

#### Objectives

- **avoid legacy** technologies, build a clear **chain of trust**, support **encrypted storage** at rest
    - use **ssh keys** as root of trust for pulumi **secrets** using **age**
    - store **secrets in repository** using pulumi stack secret
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
- create **disposable/immutable-ish** infrastructure, aim for **structural isolation** and reusability
- treat **state as code**
    - favor **state reconcilation**- and other **higher level**- tools
    - have the **complete encrypted state** in the **git repository** alongeside the code as **single source of truth**
- have a **big/full featured provision client** as the center of operation
    - target one **provision os** and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable **simulation environment** that is accurate enough for replication on production
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **jupyter notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**

#### Technologies

**Need to know** technologies (to write Deployment and Docs):
- Python, Yaml, Jinja, Systemd Service, Containerfile, Markdown

**Advanced functionality** available with knowledge of:
- pulumi, butane, fcos, saltstack, podman, compose.yml, makefile, more systemd, bash, mkdocs, mermaid, jupyter notebooks

**Tools** used:
- `pulumi` - imperativ infrastructure delaration using python
- `fcos` - Fedora-CoreOS Image with `clevis` (sss,tang,tpm) storage unlock
- `butane` - define fcos ignition using `jinja` enhanced butane yaml config
- `systemd` - os configuration using systemd: service, socket, path, timer, nspawn
- `podman` - container image builds, quadlet systemd container units, container compose socket
- `saltstack`
    - local build environment and developer related systemd user services
    - remote fcos config update using butane to saltstack translation and execution
- `tang` - unattended reboot with distributed key shards
- `age` - file and pulumi production password encryption supplied using ssh keys
- `mkdocs` - documentation using markdown and mermaid

**Operating Systems / Device Frameworks** used:
- Provision: **Arch Linux**, **Manjaro Linux** or as **Container Image**
- Server: **Fedora-CoreOS** -- updating, minimal, monolithic, container-focused operating system
- Router: **Openwrt** -- Operating system targeting embedded devices
- Automation: **Homeassistant** OS -- Open source home automation Control Bridge (Zigbee,BT,Wifi)
- IOT: **Esphome** - yaml configured **Sensor/Actor** ESP32 like **Devices** on **Arduino** or **ESP-IDF** framework

**Deploy Applications** on CoreOS using:
- `podman-systemd.unit` -- Podman systemd container units using podman-quadlet
- `systemd-nspawn` -- Spawn a OS in a light-weight container using systemd
- `compose.yml` -- Running multi-container applications defined using a Compose file

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
make container
sudo podman run -i -v $(pwd):$(pwd) provision_client /bin/bash -i
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
