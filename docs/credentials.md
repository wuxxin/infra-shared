# Credentials and Secrets Management

## Storing

- place credential in `/etc/credstore` or symlink there

## Retrieving

### Single Container

- `/etc/credstore` will be available as podman secrets
- Definition in: `<instance>.container`
```toml
[Container]
# define secret to use, optional mode and path
Secret=server.crt,mode=0640
```
- Access in Container: `/run/secrets/*`
    - `cat /run/secrets/server.crt`

### Compose Container

compose assumes docker in non swarm mode, which does not support secrets,therfore external secrets are not working. To configure local secrets credentials are configured in a systemd service dropin, that docker can pick up the credentials as local defined secrets.

- Definition in `compose@<instance>.service.d/*.conf`
```toml
[Service]
ImportCredential=server.crt
```
- Defaults
    - **root_bundle.crt**, **root_ca.crt** are already imported

- Definition `compose.yml`
```yaml
secrets:
  server.crt:
    file: ${CREDENTIALS_DIRECTORY}/server.crt

services:
  backend:
    secrets:
      - source: server.crt
```

- Access
    - outside container: `$CREDENTIALS_DIRECTORY/*`
        - `cat "$CREDENTIALS_DIRECTORY/server.crt"`
    - inside container: `/run/secrets/*`
        - `cat "/run/secrets/server.crt"`

### Nspawn Container

- Definition `systemd-nspawn@<instance>.service.d/*.conf`
```toml
# load server key as credential into systemd-nspawn
[Service]
ImportCredential=server.crt
```
- Defaults
    - **root_bundle.crt**, **root_ca.crt** are already imported

- Access: `$CREDENTIALS_DIRECTORY/*`
    - `cat "$CREDENTIALS_DIRECTORY/server.crt"`
