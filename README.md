# infra-shared

Software Defined Git Operated Infrastructure As Code.


reusables of a **learning project** by rewriting parts of my home infrastructure

as a **pulumi and core-os** based **gitops** project in **python**.


Inspired and impressed by https://github.com/deuill/coreos-home-server

See https://github.com/wuxxin/example_infra for usage in an example project

### Architecture

- **avoid legacy** technologies,
    build a clear **chain of trust**,
    **encrypted storage** at rest,
    aim for **structural isolation** and **reusability**
    - use **ssh keys** as root of trust for pulumi **secrets** using **age**
    - store **secrets in repository** using pulumi stack secret
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
    - target creating **disposable/immutable-ish** infrastructure
- have a **big/full featured provision client** as the center of operation
    - target one build os and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable **simulation environment** that is accurate enough for replication on production
- treat **state as code**
    - favor **state reconcilation** and **higher level** tools
    - have the **complete encrypted state** in the **git repository** alongeside the code
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **jupyter notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**

Tools:

- `pulumi` - imperativ infrastructure delaration using python
- `age` - file and pulumi production password encryption supplied using openssh keys
- `fcos` - Fedora-CoreOS Image with `clevis` (sss,tang,tpm) storage unlock
- `butane` - define fcos ignition using `jinja` enhanced butane yaml config
- `saltstack`
    - local build environment and file system plumbing
    - remote fcos config update using butane to saltstack translation and execution
- `tang` - unattended reboot with distributed key shards
- `vault` - some secret related (TLS-RootCerts) work
- `mkdocs` - documentation using markdown and mermaid

Operating Systems / Frameworks:

- Provision: **Arch Linux**, **Manjaro Linux** or as **Container Image**
- Server: **Fedora-CoreOS** -- updating, minimal, monolithic, container-focused operating system
- Router: **Openwrt** -- Operating system targeting embedded devices
- Automation: **Homeassistant** OS -- Open source home automation Control Bridge (Zigbee,BT,Wifi)
- IOT: **Esphome** - ESP32 based, yaml configured **Sensor/Actor** Devices based on  **Arduino** or **ESP-IDF** framework

### Usage

#### bootstrap a new repo

- from current directory, eg. pwd=~/code

```
# choose a project/directory name
project_name=example

base_dir=$(pwd)
project_dir=${base_dir}/${project_name}
mkdir -p ${project_dir}
cd ${project_dir}
git init
git submodule add https://github.com/wuxxin/infra-shared.git infra
infra/__create_project.sh
```


- See `notebooks` for jupyter notebooks of interactive pulumi, mqtt and homeassistant pyscript examples

#### install build requirements

+ on arch or manjaro linux

```sh
make install-requirements
```

+ on other linux, use a build container

```sh
make container
sudo podman run -i -v $(pwd):$(pwd) infra_build /bin/bash -i
```

#### build documentation

```sh
make docs
```

#### simulation

```sh
# all in one simstack up
make sim-up

# show root cert pem
make sim__ args="stack output ca_factory --json" | \
    jq ".root_cert_pem" -r | openssl x509 -in - -noout -text
# show provision cert
make sim__ args="stack output ca_factory --json" | \
    jq ".provision_cert_pem" -r  | openssl x509 -in - -noout -text

# manual pulumi invocation
export PULUMI_SKIP_UPDATE_CHECK=1
export PULUMI_CONFIG_PASSPHRASE=sim
pulumi stack select sim
pulumi about

# execute in python environment
pipenv run ipython

# sim stack: destroy, cleanup, preview, up
make sim-clean
make sim-create

# interactive execution of openwrt image build
pipenv run infra/tools.py sim infra.build build_openwrt

# show recorded image build salt-call stdout log output
make sim-show | jq .build_openwrt_image.result.stdout -r

# test if changes would compute before applying
make sim__ args="preview --suppress-outputs"
make sim-up
```

### production

#### create stack

```sh
make prod-create
make prod__ args="preview"
make prod__ args="up"
```
