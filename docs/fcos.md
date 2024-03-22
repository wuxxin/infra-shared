# Pulumi - Fedora CoreOS

- updating, minimal, monolithic, container-focused operating system
- available for x86 and arm

## Library Features

- Jinja templating of butane yaml content with environment vars replacement and some default vars
- Configuration and Initial Boot
    - authorized_keys, tls cert, key, ca_cert, loads container secrets
    - install extensions using rpm-ostree-install or var-local-install
- Reconfiguration / Update Configuration using translated butane to saltstack execution
- Default Services
    - `api-proxy.service`: haproxy socket to readonly http for traefik container watching
    - `frontend.service`: traefik tls termination, routing with automatic container/compose/nspawn watching
    - `dnsresolver.service`: unbound dns recursive caching resolver
- Networking
    - `.internal` bridge with dns support for internal networking
- Comfortable Deployment of
    - Single Container: `podman-systemd.unit` - systemd container units using podman-quadlet
    - Compose Container: `compose.yml` - multi-container applications defined using a compose file
    - nSpawn OS-Container: `systemd-nspawn` - an linux OS (build by mkosi) in a light-weight container

### Target Configuration

#### python configuration
+ `target/example/__init__.py`

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

#### butane configuration

+ butane files: `target/example/*.bu`
+ butane files_basedir: `target/example/`

##### overwrite of buildins

to overwrite buildins butane settings or files:

- if it is a systemd service, consider a dropin
- otherwise redefine the buildin setting or file you want to modify
    - see `butane jinja templating` for detailed ordering

### Target Update

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

### Butane Translation

#### Environment

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

#### Jinja Templating

all butane files and files referenced from butane files with attribute template=jinja
will be rendered through jinja with the described Environment and optional includes from searchpath

##### custom regex filter

- "text"|regex_escape()
- "text"|regex_search(pattern)
- "text"|regex_match(pattern)
- "text"|regex_replace(pattern, replacement)

search,match,replace support additional args
- ignorecase=True/*False
- multiline=True/*False

#### Butane Yaml

the butane configuration is created from

- base_dict    = jinja template butane_input, basedir=basedir
- security_dict= jinja template butane_security_keys, basedir=basedir
- fcos_dict    = jinja template *.bu yaml files from fcosdir
- target_dict  = jinja template *.bu yaml files from basedir
- merged_dict= fcos_dict+ target_dict+ security_dict+ base_dict
    - order is earlier gets overwritten by later

for each *.bu in fcosdir, basedir:

- from basedir/*.bu recursive read and execute jinja with environment available
- parse result as yaml
- inline all local references
    - for files and trees use source with base64 encode if file type = binary
    - storage:trees:[]:local -> files:[]:contents:inline/source
    - storage:files:[]:contents:local -> []:contents:inline/source
    - systemd:units:[]:contents_local -> []:contents
    - systemd:units:[]:dropins:[]:contents_local -> []:contents
- apply additional filter where template != ""
    - storage:files[].contents.template
    - systemd:units[].template
    - systemd:units[].dropins[].template
- merge together with additional watching for contents:inline or source

#### Ignition Json

the ignition spec file is created from the merged final butane yaml

#### Saltstack Yaml

the saltstack spec file is created from a subset of the final butane yaml

- only storage:directories/links/files and systemd:units[:dropins] are translated
- files:contents must be of type inline or source (base64 encoded)
- systemd:units and systemd:units:dropins must be of type contents
- filenames /etc/hosts, /etc/hostname, /etc/resolv.conf are translated to /host_etc/*
- append this_dir/coreos-update-config.sls and basedir/*.sls to it
- additional outputs if {UPDATE_SERVICE_STATUS} == true:
    - creates a commented, non uniqe, not sorted list of service base names
        - {UPDATE_DIR}/service_changed.req for services with changed configuration
        - {UPDATE_DIR}/service_enable.req for services to be enabled
        - {UPDATE_DIR}/service_disable.req for services to be disabled
    - `podman-systemd`, `compose.yml` and `nspawn` container:
        share the same namespace for service change recognition
        and should therefore not share the same name
    - podman-systemd container config support files (beside .container and .volume),
        should also start with the servicename as part of the filename, to be recognized
    - see `coreos-update-config.service` for detailed usage of service_*.req

### Single Container

### Compose Container

### NSpawn Container


