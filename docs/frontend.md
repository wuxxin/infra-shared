# tls/http/web FrontEnd

`traefik` is used for tls termination, http routing, middleware frontend,
for dynamic configuration of container, compose and nspawn machines using labels.

## Examples

### Single Container

- add Label and PublishPort in *instance*`.container`

```ini
[Container]
Label=traefik.enable=true
Label=traefik.http.routers.instance.rule=Host(`$HOSTNAME`)
Label=traefik.http.routers.instance.entrypoints=https
PublishPort=9043
```

### Compose Container

- add labels and expose for `instance` in compose.yml
- use `$HOSTNAME` for hostname

```yaml
services:
  thisservice:
    expose:
      - 8080
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.instance.rule=Host(`$HOSTNAME`)"
      - "traefik.http.routers.instance.entrypoints=https"
      # - "traefik.http.services.instance.loadbalancer.server.port=8080"
      # not needed if exposing a single port
```

### Nspawn Machine

- add labels and expose for `instance` in `/etc/nspawn/environment/` *instance*`.env`
- use `{{ HOSTNAME }}` for hostname
- use `##NSPAWN_IPADDR##` for ipaddress

```sh
NSPAWN_TRAEFIK="
http:
  routers:
    instance:
      rule: Host(\`instance.{{ HOSTNAME }}\`)
      service: instance
      entrypoints: https
  services:
    instance:
      loadBalancer:
        servers:
          - url: http://##NSPAWN_IPADDR##:80/
"
```
