# Config and Deploy

Library Features:

- [Jinja templating of butane](butane.md) yaml content with env vars replacement and default vars
- [Configuration](#host-configuration) and Initial Boot of CoreOS
    - coreos: updating, minimal, monolithic, container-focused os, available for x86 and arm
    - authorized_keys, loads container secrets: tls cert, key, ca_cert, ca_bundle
    - install extensions using rpm-ostree-install
- Reconfiguration / [Update Configuration](#reconfiguration) using translated butane to saltstack execution
- Services
    - [`unbound.service`](networking.md#dns-resolver): unbound as recursive dns caching resolver
    - [`knot.service`](networking.md#dns-resolver): knot as authorative, dnssec configured dns server
    - [`frontend.service`](networking.md#tlshttp-web-frontend): traefik for tls termination, middleware, container/compose/nspawn discovery
    - [Credential Management](credentials.md): store and access Credentials and other Secrets
    - [Networking](networking.md): `.internal`,`.podman[1-99]`,`.nspawn` bridges with dns support
- Deployment of
    - [Single Container](#single-container): `podman-systemd.unit` - systemd container units using podman-quadlet
    - [Compose Container](#compose-container): `compose.yml` - multi-container applications defined using a compose file
    - [nSpawn OS-Container](#nspawn-container): `systemd-nspawn` - a linux OS in a light-weight container

## Host Configuration

### python configuration

- `target/example/__init__.py`

```python
shortname = "example"
dns_names = ["example.lan"]
hostname = dns_names[0]
tls = create_host_cert(hostname, hostname, dns_names)
files_basedir = os.path.dirname(os.path.normpath(__file__))
butane_yaml = pulumi.Output.from_input("variant: fcos\nversion: 1.6.0\n")
jina_env = {}
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, jina_env
)
```

### butane configuration

create butane files in: `target/example/*.bu`

Documentation:

- [Fedora CoreOS Specification v1.6.0](https://coreos.github.io/butane/config-fcos-v1_6/)

#### overwrite of buildin files and units

it is possible to overwrite any `storage:directories,links,files` and `systemd:units[:dropins]`.
if it is a systemd service, you can also consider a dropin.

See [Butane Yaml - Merge Order](butane.md#merge-order) for detailed merge ordering

## Application Configuration

### Single Container

Documentation:

- [Podman Quadlet Systemd Units](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)

Environment:

- `/etc/containers/environment/`*instance*`.env`

Containerfile & Build Dependencies:

- `/etc/containers/build/`*instance*`/Containerfile`
- `/etc/containers/build/`*instance*`/*`

Container, Volume and Runtime Dependencies:

- `/etc/containers/systemd/`*instance*`.[container|volume]`
- `/etc/containers/systemd/`*instance*`*`
- Additional Credentials in *instance*`.container`:

    ```ini
    [Container]
    Secret=server.crt
    ```

### Compose Container

Documentation:

- [Compose File Reference](https://docs.docker.com/compose/compose-file/)

Environment:

- `/etc/compose/environment/`*instance*`.env`

Compose.yml and Build Dependencies:

- `/etc/compose/build/`*instance*`/compose.yml`
- `/etc/compose/build/`*instance*`/*`

Additional Credentials:

- `/etc/systemd/system/compose@`*instance*`.service.d/loadcreds.conf`

    ```ini
    [Service]
    ImportCredential=server.crt
    ```

### NSpawn Container

Documentation:

- [systemd.nspawn — Container settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.nspawn.html)

Environment:

- `/etc/nspawn/environment/`*instance*`.env`

`.nspawn` Configuration:

- `/etc/systemd/nspawn/`*instance*`.nspawn`

Build Dependencies:

- `/etc/systemd/system/nspawn-build@`*instance*`.service.d/*.conf`

Provision Files:

- `/etc/nspawn/build/`*instance*`/nspawn.provision.sh`
- `/etc/nspawn/build/`*instance*`/*`

Additional Credentials:

- `/etc/systemd/system/systemd-nspawn@`*instance*`.service.d/loadcreds.conf`

```ini
[Service]
ImportCredential=server.crt
```

Volumes:

- `/var/lib/volumes/`*instance*`.`*volume*`/`

## Reconfiguration

reconfigure a remote System by executing salt-call on a butane to saltstack translated config.

- Modifications to `*.bu` and their **referenced files** will result in a new config
- only the butane sections: `storage:{directories,files,links,trees}` and `systemd:unit[:dropins]` are translated

### Update Execution

1. provision: Copies systemd service and a main.sls in combination self sufficent files to the remote target
1. target: overwrite original update service, reload systemd, start update service
1. service: build update container, configure saltstack
1. service: execute salt-call of main.sls in saltstack container with mounts /etc, /var, /run from host
1. salt-call: do a mock-call first, where no changes are made, but will exit with error and stop update if call fails
1. salt-call: reconfigure of storage:{directories,files,links,trees} systemd:unit[:dropins]
1. salt-call: additional migration code written in basedir/*.sls
    - use for adding saltstack migration code to cleanup after updates, eg. deleting files and services
1. salt-call: service_enabled.list, sevice_disabled.list, service_masked.list, service_changed.list are created
1. service: systemctl daemon-reload, enable `service_enabled.list` and disable  `service_disabled.list` services
1. service: systemctl reset-failed, restart services listed in `service_changed.list`
1. service: delete main.sls and var/cache|log because of secrets and as flag that update is done

advantages of this approach:

- it can **update from a broken version of itself**
- calling a systemd service instead of calling a plain shell script for update
    - life cycle managment, independent of the calling shell, doesn't die on disconnect, has logs

the update service detects the following as changes to a service:

- systemd service `instance.(service|path|...)`
- systemd service dropin `instance.service.d/*.conf`
- local, containers and compose environment named `instance*.env`
- container file and support files named `instance.*`
- any containers build files
- any compose build files
