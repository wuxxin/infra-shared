"""
## Safe - Fedora-CoreOS on Raspberry

### config
- safe_dns_names
- identifiers["safe"]["storage"]
- tang_url

### host
- host_environment
- host_config
- host_machine
- host_update

### provider
- (postgresql.Provider): pg_server

"""

import os

import pulumi
import pulumi_postgresql as postgresql
import pulumi_random
import yaml

from infra.authority import (
    config,
    stack_name,
    ca_config,
    create_client_cert,
    create_host_cert,
    exported_ca_cert,
    ssh_factory,
)
from infra.fcos import (
    ButaneTranspiler,
    FcosConfigUpdate,
    LibvirtIgniteFcos,
    TangFingerprint,
)

this_dir = os.path.dirname(os.path.abspath(__file__))
files_basedir = os.path.join(this_dir)

shortname = "safe"
dns_names = config.get_object(
    "{}_dns_names".format(shortname),
    [
        "{}.{}".format(name, domain)
        for name in [shortname, "*." + shortname]
        for domain in ca_config["ca_permitted_domains_list"]
    ],
)
hostname = dns_names[0]
tls = create_host_cert(hostname, hostname, dns_names)

tang_url = config.get("tang_url", None)
tang_fingerprint = TangFingerprint(tang_url).result if tang_url else None

# create local postgres master password and a client_cert
pg_postgres_password = pulumi_random.RandomPassword(
    "{}_POSTGRES_PASSWORD".format(shortname), special=False, length=24
)
pg_postgres_client_cert = create_client_cert(
    "postgres@{}_POSTGRESQL_CLIENTCERT".format(shortname),
    "postgres@{}".format(hostname),
    dns_names=["postgres@{}".format(name) for name in dns_names],
)


# jinja environment for butane translation
host_environment = {
    "RPM_OSTREE_INSTALL": ["mc"],  # enable mc for debug (TODO replace with toolbox)
    "FRONTEND_DASHBOARD": "traefik.{}".format(hostname),  # enable debug dashboard
    "LOCALE": {
        key.upper(): value for key, value in config.get_object("locale").items()
    },
    "HOSTNAME": hostname,
    "ESCAPED_HOSTNAME": hostname.replace(".", "\."),
    "AUTHORIZED_KEYS": ssh_factory.authorized_keys,
    "POSTGRES_PASSWORD": pg_postgres_password.result,
}

# modify environment from config:dns if available
if config.get_object("dns", None):
    host_environment.update(
        {
            "DNS": {
                key.upper(): value for key, value in config.get_object("dns").items()
            },
        }
    )

# modify environment depending stack
if stack_name.endswith("sim"):
    # simulation adds qemu-guest-agent, debug=True, and 123 as disk passphrase
    host_environment["RPM_OSTREE_INSTALL"].append("qemu-guest-agent")
    host_environment.update({"DEBUG_CONSOLE_AUTOLOGIN": True})
    luks_root_passphrase = pulumi.Output.concat("1234")
    luks_var_passphrase = pulumi.Output.concat("1234")
    identifiers = yaml.safe_load(
        """
storage:
  - name: boot
    device: /dev/vda
    size: {size_8g}
  - name: usb1
    device: /dev/vdb
    size: {size_8g}
  - name: usb2
    device: /dev/vdc
    size: {size_8g}
""".format(size_8g=8 * pow(2, 30))
    )
else:
    # generate strong random passwords, get storage identifiers from config
    luks_root_passphrase = pulumi_random.RandomPassword(
        "{}_luks_root_passphrase".format(shortname), special=False, length=24
    ).result
    luks_var_passphrase = pulumi_random.RandomPassword(
        "{}_luks_var_passphrase".format(shortname), special=False, length=24
    ).result
    identifiers = config.get_object("identifiers")[shortname]

# update environment to include storage ids, passphrases and tang setup
host_environment.update(
    {
        "boot_device": next(
            s["device"] for s in identifiers["storage"] if s["name"] == "boot"
        ),
        "usb1_device": next(
            s["device"] for s in identifiers["storage"] if s["name"] == "usb1"
        ),
        "usb2_device": next(
            s["device"] for s in identifiers["storage"] if s["name"] == "usb2"
        ),
        "luks_root_passphrase": luks_root_passphrase,
        "luks_var_passphrase": luks_var_passphrase,
        "tang_url": tang_url,
        "tang_fingerprint": tang_fingerprint,
    }
)

# write the butane target specification
# everything else is included from files_basedir/*.bu
butane_yaml = pulumi.Output.format(
    """
variant: fcos
version: 1.5.0

"""
)

# translate butane into ignition and saltstack
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, host_environment
)
pulumi.export("{}_butane".format(shortname), host_config)

if stack_name.endswith("sim"):
    # create libvirt machine simulation
    host_machine = LibvirtIgniteFcos(
        shortname, host_config.result, volumes=identifiers["storage"], memory=4096
    )
    target = host_machine.vm.network_interfaces[0]["addresses"][0]
else:
    target = hostname

# update host to newest config, should be a no-op (zero changes) on machine creation
host_update = FcosConfigUpdate(
    shortname,
    target,
    host_config,
    opts=pulumi.ResourceOptions(depends_on=[host_machine]),
)
pulumi.export("{}_host_update".format(shortname), host_update)

# make host postgresql.Provider pg_server available
pg_server = postgresql.Provider(
    "{}_POSTGRESQL_HOST".format(shortname),
    host=target,
    username="postgres",
    password=pg_postgres_password.result,
    superuser=True,
    sslrootcert=exported_ca_cert.filename,
    sslmode="require",
    opts=pulumi.ResourceOptions(depends_on=[host_machine, host_update]),
)
