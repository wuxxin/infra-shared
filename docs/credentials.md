# Credentials

## File based Credentials

- place credential in `/etc/credstore` or symlink there

### Single Container

- files from `/etc/credstore` will be available as podman secrets
- Define in: `<instance>.container`

```ini
[Container]
# define secret to use, optional mode and path
Secret=server.crt,mode=0640
```

- Access in Container: `/run/secrets/*`
    - `cat /run/secrets/server.crt`

### Compose Container

compose assumes docker in non swarm mode, which does not support secrets,therfore external secrets are not working. To configure local secrets credentials are configured in a systemd service dropin, that docker can pick up the credentials as local defined secrets.

- Definition in `compose@<instance>.service.d/*.conf`

```ini
[Service]
ImportCredential=server.crt
```

- Defaults
    - **root_bundle.crt**, **root_ca.crt** are already imported

- Define in: `compose.yml`

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

### Nspawn Machine

- Define in: `systemd-nspawn@<instance>.service.d/*.conf`

```ini
# load server key as credential into systemd-nspawn
[Service]
ImportCredential=server.crt
```

- Defaults
    - **root_bundle.crt**, **root_ca.crt** are already imported
- Access: `$CREDENTIALS_DIRECTORY/*`
    - `cat "$CREDENTIALS_DIRECTORY/server.crt"`

## Accessing Credentials as environment variable

Secrets can also be exposed as environment variables to workloads using systemd's `LoadCredential` feature in service drop-in configuration files.

- Create the credential file in `/etc/credstore/mysecret.env` with the following format:

```
MY_SECRET=myvalue
```

### Single Container

- Define in: `<instance>.container`

```ini
[Service]
LoadCredential=mysecret.env
```

- The secret will be available as an environment variable inside the container.

### Compose Container

- Define in: `compose@<instance>.service.d/*.conf`

```ini
[Service]
LoadCredential=mysecret.env
```

- The secret will be available as an environment variable inside the container.

### Nspawn Machine

- Define in: `systemd-nspawn@<instance>.service.d/*.conf`

```ini
[Service]
LoadCredential=mysecret.env
```

- The secret will be available as an environment variable inside the nspawn machine.

