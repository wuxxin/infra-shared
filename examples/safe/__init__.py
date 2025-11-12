"""
## Safe - Fedora-CoreOS on Raspberry PI

### config
- safe_dns_names: defaults to ["*.safe" for each authority.ca_config["ca_permitted_domains_list"]]
- identifiers["safe"]["storage"]: production storage device serial numbers
- tang_url
- safe_showcase_compose:    *true,  if false, dont include compose showcase
- safe_showcaae_nspawn:     *true,  if false, dont include nspawn showcase
- safe_showcase_unittest:   *false, if true,  dont spawn vm but finish with vm config

### host
- host_environment
- host_config
- host_machine
- host_update

### provider
- postgresql.Provider: pg_server

"""

import os
import sys

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
    ServePrepare,
    ServeOnce,
    WaitForHostReady,
    write_removable,
    public_local_export,
)
from infra.build import build_raspberry_extras

this_dir = os.path.dirname(os.path.normpath(__file__))
files_basedir = os.path.join(this_dir)

# configure hostnames
shortname = "safe"
dns_names = config.get_object("{}_dns_names".format(shortname)) or [
    "{}.{}".format(name, domain)
    for name in [shortname, "*." + shortname]
    for domain in ca_config["ca_permitted_domains_list"]
]
hostname = dns_names[0]

# create tls host certificate
tls = create_host_cert(hostname, hostname, dns_names)

# get tang config for storage unlock on boot
tang_url = config.get("tang_url")
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
pulumi.export(f"{hostname}_postgres_client_cert", pg_postgres_client_cert)


# jinja environment for butane config
host_environment = {
    # install mc on sim, prod should use toolbox
    "RPM_OSTREE_INSTALL": ["mc", "strace"] if stack_name.endswith("sim") else [],
    "SHOWCASE_COMPOSE": config.get(shortname + "_showcase_compose")
    in (None, True, "true", "True"),
    "SHOWCASE_NSPAWN": config.get(shortname + "_showcase_nspawn")
    in (None, True, "true", "True"),
    "SHOWCASE_UNITTEST": config.get(shortname + "_showcase_unittest")
    in (True, "true", "True"),
    "AUTHORIZED_KEYS": ssh_factory.authorized_keys,
    "POSTGRESQL_PASSWORD": pg_postgres_password.result,
    # make postgresql public available
    "POSTGRESQL_PUBLIC_MTLS": True,
    "POSTGRESQL_PUBLIC_PWD": True,
    "DNS_RESOLVER": {}
    if not config.get_object("dns_resolver")
    else {key.upper(): value for key, value in config.get_object("dns_resolver").items()},
    "LOCAL_DNS_SERVER": {"ENABLED": True},
    "LOCAL_ACME_SERVER": {"ENABLED": True},
    "PODMAN_STATIC_NETWORKS": {"pgmtls": "10.89.128.1/24", "pgpwd": "10.89.129.1/24"},
    "FRONTEND": {
        # enable debug dashboard
        "DASHBOARD": "traefik.{}".format(hostname),
        # enable tls for tang at port 9443, postgresql on port 5432 and 5431
        "PUBLISHPORTS": ["9443:9443", "5432:5432", "5431:5431"],
        # also listen to pgmtls and pgpwd networks, to have postgresql distinct the authentication
        "NETWORKS": ["pgmtls:ip=10.89.128.1", "pgpwd:ip=10.89.129.1"],
        "ENTRYPOINTS": {
            "tang-mtls-nosni": {
                "address": ":9443",
                "http": {"tls": {"options": "mtls-nosni@file"}},
            },
            "pgmtls": {"address": ":5432"},
            "pgpwd": {"address": ":5431"},
        },
        "EXTRA": 'accessLog:\n  format: "common"',
    },
}


# modify environment config depending stack for storage and credentials
if stack_name.endswith("sim"):
    # for simulation: add qemu-guest-agent, debug=True, and 1234 as disk passphrase
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
    # for production: generate strong random passwords, get storage identifiers from config
    luks_root_passphrase = pulumi_random.RandomPassword(
        "{}_luks_root_passphrase".format(shortname), special=False, length=24
    ).result
    luks_var_passphrase = pulumi_random.RandomPassword(
        "{}_luks_var_passphrase".format(shortname), special=False, length=24
    ).result
    identifiers = config.get_object("identifiers")[shortname]

# update environment to include storage id's, passphrases and tang setup
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
butane_yaml = pulumi.Output.from_input(
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

# configure the later used remote url for remote controlled setup with encrypted config
serve_config = ServePrepare(
    shortname,
    serve_interface="virbr0" if stack_name.endswith("sim") else "",
    request_header={
        "Verification-Hash": host_config.ignition_config_hash,
    },
)

# create public ignition config pointing to https retrieval of host_config served by ServeOnce
public_config = RemoteDownloadIgnitionConfig(
    "{}_public_ignition".format(shortname),
    hostname,
    remote_url=serve_config.config.apply(lambda x: x["remote_url"]),
    remote_hash=host_config.ignition_config_hash,
    opts=pulumi.ResourceOptions(ignore_changes=["stdin"]),
)

# only simulate SystemConfigUpdate, skip rest if unittest
if host_environment["SHOWCASE_UNITTEST"]:
    host_update = SystemConfigUpdate(
        shortname,
        hostname,
        host_config,
        simulate=True,
    )
    pulumi.export("{}_host_update".format(shortname), host_update)
else:
    # serve secret part of ignition config via ServeOnce
    serve_data = ServeOnce(
        shortname,
        config=serve_config.config,
        payload=host_config.result,
        opts=pulumi.ResourceOptions(ignore_changes=["stdin"]),
    )
    pulumi.export("{}_served_once".format(shortname), serve_data)

    if stack_name.endswith("sim"):
        # create libvirt machine simulation:
        #   download suitable image, create similar virtual machine, same memsize, different arch
        host_machine = LibvirtIgniteFcos(
            shortname,
            public_config.result,
            volumes=identifiers["storage"],
            memory=4096,
        )
        # write out ip of simulated host as target
        target = host_machine.vm.network_interfaces[0]["addresses"][0]
        opts = pulumi.ResourceOptions(depends_on=[host_machine, serve_data])
    else:
        # download metal version of ARM64 os image (Raspberry PI compatible)
        image = FcosImageDownloader(
            architecture="aarch64", platform="metal", image_format="raw.xz"
        )

        # download bios and other extras for Raspberry PI for customization
        extras = build_raspberry_extras()
        uboot_image_filename = os.path.join(
            extras.config["grains"]["tmp_dir"], "uboot/boot/efi/u-boot.bin"
        )

        # export public config to be copied to the removable storage device
        public_config_file = public_local_export(
            shortname, "{}_public.ign".format(shortname), public_config.result
        )

        # write customized image to removable storage device, include uboot image and ignition config
        host_boot_media = write_removable(
            shortname,
            image=image.imagepath,
            serial=host_environment["boot_device"].strip("/dev/disk/by-uuid/"),
            patches=[
                (uboot_image_filename, "EFI-SYSTEM/boot/efi/u-boot.bin"),
                (public_config_file.filename, "boot/ignite.json"),
            ],
        )

        # target is metal, write out real dns name
        target = hostname
        opts = pulumi.ResourceOptions(depends_on=[host_boot_media, serve_data])

    # wait until host is ready
    host_ready = WaitForHostReady(
        shortname,
        target,
        user=host_config.this_env.apply(lambda env: env["UPDATE_USER"]),
        private_key=ssh_factory.provision_key.private_key_openssh,
        # isready checks for running unbound, which means after rpm-ostree has run and the machine rebooted and started
        isready_cmd="/usr/sbin/systemctl is-active unbound",
        opts=opts,
    )

    # update host to newest config, should be a no-op (zero changes) on machine creation
    host_update = SystemConfigUpdate(
        shortname,
        target,
        host_config,
        simulate=False,
        opts=pulumi.ResourceOptions(depends_on=[host_ready]),
    )
    pulumi.export("{}_host_update".format(shortname), host_update)

    # make host postgresql.Provider pg_server available
    # print(f"exported_ca_cert.filename: {exported_ca_cert.filename}", file=sys.stderr)

    pg_server = postgresql.Provider(
        "{}_POSTGRESQL_HOST".format(shortname),
        host=hostname,
        username="postgres",
        password=pg_postgres_password.result,
        # XXX currently either mtls or password can be configured and used, therefore password is activated.
        # XXX parsing the sslrootcert in this provider from file currently doesnt work if client cert is activated (for whatever reason)
        # clientcert=postgresql.ProviderClientcertArgs(
        #     cert=pg_postgres_client_cert.chain,
        #     key=pg_postgres_client_cert.key.private_key_pem,
        #     sslinline=True,
        # ),
        superuser=True,
        sslrootcert=exported_ca_cert.filename,
        sslmode="verify-ca",
        opts=pulumi.ResourceOptions(depends_on=[host_update]),
    )
    pulumi.export("{}_pg_server".format(shortname), pg_server)
