# Config and Deploy OS

Library Features:

- [Jinja templating of butane](butane.md) yaml content with env vars replacement and default vars
- [Configuration](#host-configuration) and Initial Boot of CoreOS
    - coreos: updating, minimal, monolithic, container-focused os, available for x86 and arm
    - authorized_keys, loads container secrets: tls cert, key, ca_cert, ca_bundle
    - install extensions using rpm-ostree-install
- Reconfiguration / [Update Configuration](update.md) using translated butane to saltstack execution
- Services
    - [`unbound.service`](networking.md#dns-resolver): unbound as recursive dns caching resolver
    - [`frontend.service`](networking.md#tlshttp-web-frontend): optional traefik tls termination, middleware, container/compose/nspawn discovery
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
files_basedir = os.path.dirname(os.path.abspath(__file__))
butane_yaml = pulumi.Output.format("variant: fcos\nversion: 1.5.0\n")
jina_env = { "HOSTNAME": hostname}
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, jina_env
)
```

### butane configuration

create butane files in: `target/example/*.bu`

Documentation:

- [Fedora CoreOS Specification v1.5.0](https://coreos.github.io/butane/config-fcos-v1_5/)

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
