"""
## Safe - Fedora-CoreOS on Raspberry PI

### config
- safe_dns_names: defaults to ["*.safe" for each authority.ca_config["ca_permitted_domains_list"]]
- identifiers["safe"]["storage"]: production storage device serial numbers
- tang_url
- safe_showcase_compose: true, if false, dont include compose showcase
- safe_showcaae_nspawn: true, if false, dont include nspawn showcase

### host
- host_environment
- host_config
- host_machine
- host_update

### provider
- postgresql.Provider: pg_server

"""

import os
import copy

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
from infra.os import (
    ButaneTranspiler,
    SystemConfigUpdate,
    LibvirtIgniteFcos,
    TangFingerprint,
    FcosImageDownloader,
    RemoteDownloadIgnitionConfig,
)
from infra.tools import (
    serve_prepare,
    serve_once,
    write_removeable,
    public_local_export,
    log_warn,
)
from infra.build import build_raspberry_extras

this_dir = os.path.dirname(os.path.abspath(__file__))
files_basedir = os.path.join(this_dir)

# configure hostnames
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

# create tls host certificate
tls = create_host_cert(hostname, hostname, dns_names)

# get tang config
tang_url = config.get("tang_url", None)
tang_fingerprint = TangFingerprint(tang_url).result if tang_url else None

# create local postgres master password
pg_postgres_password = pulumi_random.RandomPassword(
    "{}_POSTGRES_PASSWORD".format(shortname), special=False, length=24
)

# create a postgres master client_cert
pg_postgres_client_cert = create_client_cert(
    "postgres@{}_POSTGRESQL_CLIENTCERT".format(shortname),
    "postgres@{}".format(hostname),
    dns_names=["postgres@{}".format(name) for name in dns_names],
)


# jinja environment for butane translation
host_environment = {
    # install mc on sim, prod should use toolbox
    "RPM_OSTREE_INSTALL": ["mc"] if stack_name.endswith("sim") else [],
    "FRONTEND": {
        # enable debug dashboard
        "DASHBOARD": "traefik.{}".format(hostname),
        # enable tls for tang at port :9443
        "PUBLISHPORTS": ["9443:9443"],
        "ENTRYPOINTS": {
            "tang-mtls-nosni": {
                "address": ":9443",
                "http": {"tls": {"options": "mtls-nosni@file"}},
            }
        },
        "EXTRA": 'accessLog:\n  format: "common"',
    },
    "LOCALE": {
        key.upper(): value for key, value in config.get_object("locale").items()
    },
    "DNS_RESOLVER": {}
    if not config.get_object("dns_resolver", None)
    else {
        key.upper(): value for key, value in config.get_object("dns_resolver").items()
    },
    "AUTHORIZED_KEYS": ssh_factory.authorized_keys,
    "POSTGRES_PASSWORD": pg_postgres_password.result,
    "SHOWCASE_COMPOSE": config.get(shortname + "_showcase_compose", True),
    "SHOWCASE_NSPAWN": config.get(shortname + "_showcase_nspawn", True),
}


# modify storage and credentials related config depending stack
if stack_name.endswith("sim"):
    # simulation adds qemu-guest-agent, debug=True, and 1234 as disk passphrase
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

# write the butane target specification, everything else is included from files_basedir/*.bu
butane_yaml = pulumi.Output.format(
    """
variant: fcos
version: 1.6.0
"""
)

# translate butane into ignition and saltstack
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, host_environment
)
pulumi.export("{}_butane".format(shortname), host_config)

# download metal version of os image
image = FcosImageDownloader(
    architecture="aarch64", platform="metal", image_format="raw.xz"
)

# download bios and other extras for customization
extras = build_raspberry_extras()
uboot_image_filename = os.path.join(
    extras.config["grains"]["tmp_dir"], "uboot/boot/efi/u-boot.bin"
)

# configure later used remote url for remote controlled setup with encrypted config
# XXX config_input=f"mtls_clientid: install@{hostname}"
serve_config = serve_prepare(shortname, timeout_sec=120)
remote_url = serve_config.config["remote_url"]

# create a 1 day valid client certificate only used for transfering the ignition file
custom_ca_config = copy.copy(ca_config)
custom_ca_config["cert_validity_period_hours"] = 24
custom_ca_config["cert_early_renewal_hours"] = 1
host_install_cert = create_client_cert(
    f"install@{hostname}", f"install@{hostname}", custom_ca_config=custom_ca_config
)
# create public ignition config
public_config = RemoteDownloadIgnitionConfig(
    "{}_public_ignition".format(shortname),
    hostname,
    remote_url,
)

# serve secret part of ignition config via serve_once and mandatory client certificate
serve_data = serve_once(
    shortname,
    payload=pulumi.Output.all(source_dict=host_config.result).apply(
        lambda args: yaml.safe_dump(args["source_dict"])
    ),
    config=serve_config,
)

if stack_name.endswith("sim"):
    # create libvirt machine simulation:
    #   download suitable image, create similar virtual machine, same memsize, different arch
    host_machine = LibvirtIgniteFcos(
        shortname, public_config.result, volumes=identifiers["storage"], memory=4096
    )
    # write out ip of simulated host as target
    target = host_machine.vm.network_interfaces[0]["addresses"][0]
    opts = pulumi.ResourceOptions(depends_on=[host_machine, serve_data])
else:
    # export public config to be copied to the removeable storage device
    public_config_file = public_local_export(
        shortname, "{}_public.ign".format(shortname), public_config.result
    )

    # write customized image to removeable storage device, include uboot image and ignition config
    host_boot_media = write_removeable(
        shortname,
        image=image.imagepath,
        serial=host_environment["bootdevice"].strip("/dev/disk/by-uuid/"),
        patches=[
            (uboot_image_filename, "EFI-SYSTEM/boot/efi/u-boot.bin"),
            (public_config_file.filename, "boot/ignite.json"),
        ],
    )

    # target is metal, write out real dns name
    target = hostname
    opts = pulumi.ResourceOptions(depends_on=[host_boot_media, serve_data])


# update host to newest config, should be a no-op (zero changes) on machine creation
host_update = SystemConfigUpdate(
    shortname, target, host_config, simulate=False, opts=opts
)
pulumi.export("{}_host_update".format(shortname), host_update)

# make host postgresql.Provider pg_server available
pg_server = postgresql.Provider(
    "{}_POSTGRESQL_HOST".format(shortname),
    host=target,
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
    opts=pulumi.ResourceOptions(depends_on=[host_machine, host_update]),
)
