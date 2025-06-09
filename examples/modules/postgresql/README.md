# Postgresql Module

## HowTo

### Config

- symlink as `postgresql`to your target basedir
- check if HOSTNAME and LOCALE["LANG"] of config are suited or override them in environment

#### Environment: POSTGRES_PASSWORD

```python
import pulumi_random

# update needed environment config
pg_postgres_password = pulumi_random.RandomPassword(
    "{}_POSTGRES_PASSWORD".format(shortname), special=False, length=24
)
host_environment.update({"POSTGRES_PASSWORD": pg_postgres_password.result})
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
    sslmode="require",
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

locale = config.get_object("locale")

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
