# Postgresql Module

## HowTo

### Files

- [module.bu](module.bu.md)
- [postgresql.conf](container/postgresql.conf.md)
- [postgresql.container](container/postgresql.container.md)
- [postgresql.volume](container/postgresql.volume.md)
- [Containerfile](Containerfile/postgresql/Containerfile.md)

### Config

- symlink as `postgresql`to your target basedir

#### Environment

- check `LOCALE["LANG"]` of config are suited or override them in environment
- create `POSTGRESQL_PASSWORD`

```python
import pulumi_random

# update needed environment config
pg_postgresql_password = pulumi_random.RandomPassword(
    "{}_POSTGRESQL_PASSWORD".format(shortname), special=False, length=24
)
host_environment.update({"POSTGRESQL_PASSWORD": pg_postgresql_password.result})
```

- expose postgresql also to the public interface

```python
# enable postgresql on public port 5432 with mtls authentication
# enable postgresql on public port 5431 with password authentication
host_environment.update({"POSTGRESQL_PUBLIC_MTLS": True, "POSTGRESQL_PUBLIC_PWD": True})
# enable frontend container to listen to public ports 5432 and 5431
for port in ["5432:5432", "5431:5431"]:
    if port not in host_environment["FRONTEND"]["PUBLISH_PORTS"]:
        host_environment["FRONTEND"]["PUBLISH_PORTS"].append([port])
# configure these ports in traefik as entrypoints pgmtls and pgpwd for frontend
for name, config in [("pgmtls", {"address": ":5432"}), ("pgpwd", {"address": ":5431"})]:
    if name not in host_environment["FRONTEND"]["ENTRYPOINTS"]:
        host_environment["FRONTEND"]["ENTRYPOINTS"].update({name: config})
# define static networks needed for MTLS,PWD distinction
host_environment["PODMAN_STATIC_NETWORKS"].update(
    {"pgmtls": "10.89.128.1/24", "pgpwd": "10.89.129.1/24"}
)
# connect additional networks pgmtls and pgpwd to frontend container for mtls,pwd distinction
for network in [
    f"pgmtls:ip={host_environment['PODMAN_STATIC_NETWORKS']['pgmtls'].strip('/24')}",
    f"pgpwd:ip={host_environment['PODMAN_STATIC_NETWORKS']['pgpwd'].strip('/24')}",
]:
    if network not in host_environment["FRONTEND"]["NETWORKS"]:
        host_environment["FRONTEND"]["NETWORKS"].append([network])

```

#### Provider: create POSTGRESQL-Provider

```python
import pulumi
import pulumi_postgresql as postgresql

# make host postgresql.Provider pg_server available
pg_server = postgresql.Provider(
    "{}_POSTGRESQL_HOST".format(shortname),
    host=hostname,
    username="postgres",
    password=pg_postgres_password.result,
    # clientcert=postgresql.ProviderClientcertArgs(
    #     key=pg_postgres_client_cert.key.private_key_pem,
    #     cert=pg_postgres_client_cert.chain,
    #     sslinline=True,
    # ),
    superuser=True,
    sslrootcert=exported_ca_cert.filename,
    sslmode="verify-ca",
    opts=pulumi.ResourceOptions(depends_on=[host_update]),
)
pulumi.export("{}_pg_server".format(shortname), pg_server)
```

### Usage

#### Create Database and User on pg_server host Postgresql

```python
import pulumi
import pulumi_random
import pulumi_postgresql as postgresql

import infra.os

locale = infra.os.get_locale()

ha_user_password = pulumi_random.RandomPassword(
    "{}_POSTGRESQL_PASSWORD".format("homeassistant"), special=False, length=24
)
ha_user = postgresql.Role(
    "homeassistant_POSTGRESQL_ROLE",
    name="homeassistant",
    login=True,
    password=ha_user_password.result,
    skip_drop_role=True,
    opts=pulumi.ResourceOptions(provider=pg_server),
)
ha_db = postgresql.Database(
    "homeassistant_POSTGRESQL_DATABASE",
    name="homeassistant",
    owner="homeassistant",
    lc_collate=locale["lang"],
    lc_ctype=locale["lang"],
    opts=pulumi.ResourceOptions(provider=pg_server, depends_on=[ha_user]),
)
```
