# Fedora CoreOS

Fedora CoreOS:

- updating, minimal, monolithic, container-focused operating system
- available for x86 and arm

Library Features:

- [Jinja templating of butane](butane.md) yaml content with env vars replacement and default vars
- [Configuration](#host-configuration) and Initial Boot
    - authorized_keys, loads container secrets: tls cert, key, ca_cert, ca_bundle
    - install extensions using rpm-ostree-install or var-local-install
- Reconfiguration / [Update Configuration](#host-update) using translated butane to saltstack execution
- Services
    - [`unbound.service`](dnsresolver.md): unbound as recursive dns caching resolver
    - [`frontend.service`](frontend.md): optional traefik tls termination, middleware, container/compose/nspawn discovery
    - [Credential and Secrets Management](credentials.md): store and access Credentials
    - [Networking](networking.md): `.internal`,`.podman[1-99]`,`.nspawn` bridges with dns support
- Deployment of
    - [Single Container](#single-container): `podman-systemd.unit` - systemd container units using podman-quadlet
    - [Compose Container](#compose-container): `compose.yml` - multi-container applications defined using a compose file
    - [nSpawn OS-Container](#nspawn-container): `systemd-nspawn` - a linux OS in a light-weight container

### Host Configuration

#### python configuration
+ `target/example/__init__.py`

```python
this_dir = os.path.dirname(os.path.abspath(__file__))
files_basedir = this_dir
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
    - see [Butane Yaml - Merge Order](butane.md#merge-order) for detailed ordering

### Host Update

reconfigure a remote CoreOS System by executing salt-call on a butane to saltstack translated config

Modifications to *.bu and their referenced files will result in a new saltstack config

- Copies systemd.service and a main.sls in combination self sufficent files to the remote target
- overwrite original update service, reload systemd, start service, build container, configure salt
- execute main.sls in an saltstack container where /etc, /var, /run is mounted from the host
- only the butane sections: storage:{directories,files,links,trees} systemd:unit[:dropins] are translated
- additional migration code can be written in basedir/*.sls
    - use for adding saltstack migration code to cleanup after updates, eg. deleting files and services
- advantages of this approach
    - it can **update from a broken version of itself**
    - calling a systemd service instead of calling a plain shell script for update
        - life cycle managment, independent of the calling shell, doesn't die on disconnect, has logs

### Application Configuration

#### Single Container

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

#### Compose Container

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

#### NSpawn Container

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

### Administration

- use `toolbox create` and `toolbox enter` to have a fedora container available.
- use `dnf install package` to install packages inside toolbox.

