# Pulumi - Fedora CoreOS

- updating, minimal, monolithic, container-focused operating system
- available for x86 and arm

## Library Features

- Jinja templating of butane yaml content with environment vars replacement and some default vars
- Configuration and Initial Boot
    - authorized_keys, tls cert, key, ca_cert, loads container secrets
    - install extensions using rpm-ostree-install or var-local-install
- Reconfiguration / Update Configuration using translated butane to saltstack execution
- Comfortable Deployment of
    - Single Container: `podman-systemd.unit` - systemd container units using podman-quadlet
    - Compose Container: `compose.yml` - multi-container applications defined using a compose file
    - nSpawn OS-Container: `systemd-nspawn` - an linux OS (build by mkosi) in a light-weight container

### Target Configuration

+ python configuration: `target/example/__init__.py`

```python
this_dir = os.path.dirname(os.path.abspath(__file__))
files_basedir = os.path.join(this_dir)
shortname = "example"
dns_names = ["example.lan"]
hostname = dns_names[0]
tls = create_host_cert(hostname, hostname, dns_names)
butane_yaml = pulumi.Output.format("variant: fcos\nversion: 1.5.0\n")
host_config = ButaneTranspiler(
    shotname, hostname, tls, butane_yaml, files_basedir, host_environment
)
```

+ butane configuration: `target/example/*.bu`
+ butane includes files_basedir: `target/example/`

#### Single Container

#### Compose Container

#### NSpawn Container

### Default Services
#### frontend.service
- traefik tls termination, routing

#### api-proxy.service
- haproxy socket to readonly http for traefik container watching

#### dnsresolver.service
- unbound dns recursive caching resolver

### FcosConfigUpdate

reconfigure a remote CoreOS System by executing salt-call on a butane to saltstack translated config

Modifications to *.bu and their referenced files will result in a new saltstack config

- Copies two (systemd.service and a main.sls) in combination self sufficent files to the remote target
- overwrite original update service, reload systemd, start service, build container, configure salt
- execute main.sls in an saltstack container where /etc, /var, /run is mounted from the host
- only the butane sections: storage:{directories,files,links,trees} systemd:unit[:dropins] are translated
- additional migration code can be written in basedir/*.sls
    - use for adding saltstack migration code to cleanup after updates, eg. deleting files and services
- advantages of this approach
    - it can **update from a broken version of itself**
    - calling a systemd service instead of calling a plain shell script for update
        - life cycle managment, independent of the calling shell, doesn't die on disconnect, has logs

## Usage and Customization

- `authority.py` - TLS Certificate-Authority, functions for TLS Certificates and SSH-Provision
- `tools.py` - SSH copy/deploy/execute functions, local and remote Salt-Call
- `build.py` - build Embedded-OS Images and IOT Images
    - **Raspberry Extras** - U-Boot and UEFI Bios Files for Rpi3 and Rpi4
    - **Openwrt Linux** - Network Device Distribution for Router and other network devices
- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `write_removeable.py` - write image to removable storage specified by serial_number
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN

how to overwrite buildins butane config or files:

- if it is a systemd service, consider a dropin
- in other cases, simple redefine setting/file, it will overwrite any buildin file/config

### Butane Transpiler

environment defaults available in jinja (for details see DEFAULT_ENV_STR):

- Boolean DEBUG
- Boolean UPDATE_SERVICE_STATUS
- Boolean CONTAINER_FRONTEND
- Boolean DNS_RESOLVER
- String  FRONTEND_DASHBOARD
- String  INTERNAL_CIDR
- String  PODMAN_CIDR
- Dict LOCALE: {LANG, KEYMAP, TIMEZONE, COUNTRY_CODE}
- List RPM_OSTREE_INSTALL

butane jinja templating:

1. jinja template butane_input, basedir=basedir
2. jinja template butane_security_keys, basedir=basedir
3. jinja template *.bu yaml from this_dir, basedir=subproject_dir
    - inline all local references including storage:trees as storage:files
4. jinja template *.bu yaml files from basedir
    - merge order= butane_input -> butane_security -> this_dir*.bu -> basedir/*.bu
5. apply additional filters where butane extension template != None
    - template=jinja: template through jinja
    - storage:files[].contents.template
    - systemd:units[].template
    - systemd:units[].dropins[].template
6. translate merged butane yaml to saltstack salt yaml config
    - jinja templating of butane2salt.jinja with butane_config as additional environment
    - append this_dir/coreos-update-config.sls and basedir/*.sls to it
7. translate merged butane yaml to ignition json config

#### butane to salt translation

translates and inlines a subset of butane spec into a one file saltstack salt spec

- Only the currently used subset in *.bu files of the butane spec is supported
  - only storage:directories/links/files/trees and systemd:units[:dropins] are translated
  - Filenames /etc/hosts, /etc/hostname, /etc/resolv.conf are translated to /host_etc/*

- Look at tools.jinja_run for custom filter like traverse files or regex_replace
- use 'import "subdir/filename" as contents' to import from basedir/subdir/filename

additional outputs if {UPDATE_SERVICE_STATUS} == true:

- creates a commented, non uniqe, not sorted list of service base names
  - {UPDATE_DIR}/service_changed.req for services with changed configuration
  - {UPDATE_DIR}/service_enable.req for services to be enabled
  - {UPDATE_DIR}/service_disable.req for services to be disabled

- usage example:
```sh
cat ${UPDATE_DIR}/service_changed.req | grep -v "^#" | \
    grep -v "^[[:space:]]*$" | sort | uniq
```


### Architecture


#### Objectives

- **avoid legacy** technologies, build a clear **chain of trust**, support **encrypted storage** at rest
    - use **ssh keys** as root of trust for pulumi **stack secret** using **age**
    - store **secrets in the repository** using pulumi config secrets
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
- create **disposable/immutable-ish** infrastructure, aim for **structural isolation** and reusability
- treat **state as code**, favor **state reconcilation** tools
    - have the **complete encrypted state** in the **git repository** as **single source of truth**
- have a **big/full featured provision client** as the center of operation
    - target one **provision os** and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable local **simulation environment** with **fast reconfiguration** turnaround
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **jupyter notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**
