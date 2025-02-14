# Networking

## Internal Networks

**10.87.X.X - 10.89.X.X** are used for internal networking

- `.internal` bridge with dns support
- `.podman[1-99]` bridge with dns support and dns resolution for `.podman` container
- `.nspawn` bridge with dns support and dns resolution for `.nspawn` container

## DNS-Resolver

DNS Resolver for System, Container, Compose and Nspawn workloads is done using `Unbound`.

- available under `dns.internal` on `udp/53`, `tcp/53` and `DoT:tcp/853`
- default upstream is **split round robin DoT (DNS over TLS)**
    - over 2x dns.google, 2x dns-unfiltered.adguard.com, 2x cloudflare-dns.com
- dynamic name and reverse ptr resolution for
    - `.podman` Container and Compose workloads
    - `.nspawn` Machine Container

Documentation:

- [Unbound Documentation](https://unbound.docs.nlnetlabs.nl/en/latest/)

### Examples

#### forward custom zones to another dns server

```yaml
DNS_RESOLVER:
  FORWARD:
    - name: lan
      addr: 127.0.0.1@5353
      tls: false
    - name: 30.9.10.in-addr.arpa
    - addr: 127.0.0.1@5353
      tls: false
```

#### add custom zone entries and public dns overrides

```yaml
DNS_RESOLVER:
  SRV: |
    # STRING, appended to SRV section

    # A Record
    local-data: 'somecomputer.local. A 192.168.1.1'

    # PTR Record
    local-data-ptr: '192.168.1.1 somecomputer.local.'

    # local zone '.whatever'
    local-zone: 'whatever.' static
    local-data: 'me.whatever. A 192.168.2.1'

    # additional access control
    access-control: 192.168.2.0/24 allow

    # override public dns entry
    local-data: 'checkonline.home-assistant.io. 300 IN A 1.2.3.4'

```

#### use non tls custom upstream

```yaml
DNS_RESOLVER:
  UPSTREAM:
    # list of ip@port
    - 1.2.3.4@53
  UPSTREAM_TLS: false
```

#### add custom unbound config string

```yaml
DNS_RESOLVER:
  EXTRA: |
    # STRING, appended to config file must start with a section
    [section-of-unbound.conf]
    # see https://unbound.docs.nlnetlabs.nl/en/latest/

```

## tls/http Web-Frontend

`traefik` is used for tls termination, http routing, middleware frontend,
for dynamic configuration of container, compose and nspawn machines using labels.

Documentation:

- [Traefik Documentation](https://doc.traefik.io/traefik/)

### Customization

#### custom entrypoints and published ports

```yaml
FRONTEND:
  ENTRYPOINTS:
    tang_https:
      address: ":9443"
      http:
        tls:
          options: mtls@file
  PUBLISHPORTS:
    - "9943:9943"
```

#### custom providers

```yaml
FRONTEND:
  PROVIDERS:
    file:
      directory: /traefik
      watch: true
```

#### additional traefik config string

```yaml
FRONTEND:
  EXTRA: |
    # STRING, appended to traefik.static.yml

```

### Web Usage Examples

#### Single Container

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

#### Compose Container

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

#### Nspawn Machine

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
