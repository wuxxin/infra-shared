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
    - `apiproxy.service`: haproxy socket to readonly http for traefik container watching
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
    + target/example/main.bu
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

### Single Container

### Compose Container

### NSpawn Container


