# tls/http Web-Frontend

`traefik` is used for tls termination, http routing, middleware frontend,
for dynamic configuration of container, compose and nspawn machines using labels.

## Examples

### Single Container

- add environment for `instance` in `/etc/containers/environment/` *instance*`.env`
```sh
HOSTNAME=instance.hostname.domain
```

- use **`${HOSTNAME}`** for hostname

- add Label in *instance*`.container`

```ini
[Container]
Label=traefik.enable=true
Label=traefik.http.routers.instance.rule=Host(`${HOSTNAME}`)
Label=traefik.http.routers.instance.entrypoints=https

# use [Container]EnvironmentFile= ... if you need environment inside the container
# EnvironmentFile=/etc/containers/environment/%N.env

[Service]
# use [Service]EnvironmentFile= ... if you need environment in the systemd service
EnvironmentFile=/etc/containers/environment/%N.env

```

### Compose Container

- add environment for `instance` in `/etc/compose/environment/` *instance*`.env`
```sh
HOSTNAME=instance.hostname.domain
```
- add labels and expose for `instance` in compose.yml
- use **`${HOSTNAME}`** for hostname

```yaml
services:
  thisservice:
    expose:
      - 8080
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.instance.rule=Host(`${HOSTNAME}`)"
      - "traefik.http.routers.instance.entrypoints=https"
      # - "traefik.http.services.instance.loadbalancer.server.port=8080"
      # not needed if exposing a single port
```

### Nspawn Machine

- add labels and expose for `instance` in `/etc/nspawn/environment/` *instance*`.env`
- use `{{ HOSTNAME }}` for hostname
- use `$IPADDR` inside NSPAWN_TRAEFIK to replace with the current machine ip
- escape backticks ` with two backslashes \\\\


```sh
NSPAWN_TRAEFIK="
http:
  routers:
    instance:
      rule: Host(\\`instance.{{ HOSTNAME }}\\`)
      service: instance
      entrypoints: https
  services:
    instance:
      loadBalancer:
        servers:
          - url: http://$IPADDR:80/
"
```
