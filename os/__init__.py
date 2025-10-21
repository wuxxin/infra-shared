"""
## Pulumi - CoreOS Centric System Config, Deployment, Operation, Update

### Components

- ButaneTranspiler
- WaitForHostReady
- SystemConfigUpdate
- FcosImageDownloader
- LibvirtIgniteFcos
- TangFingerprint
- RemoteDownloadIgnitionConfig

### Functions

- butane_clevis_to_json_clevis

"""

import glob
import os
import re
import sys
import json

import pulumi
import pulumi_command as command
from pulumi_command.local import Logging as LocalLogging

import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl
import yaml

from ..tools import log_warn
from ..template import (
    jinja_run,
    jinja_run_file,
    load_butane_dir,
    butane_to_salt,
    join_paths,
    merge_dict_struct,
    merge_butane_dicts,
)

this_dir = os.path.dirname(os.path.abspath(__file__))
subproject_dir = os.path.abspath(os.path.join(this_dir, ".."))


def butane_clevis_to_json_clevis(butane_config):
    """
    Parses a Butane config dictionary and returns JSON strings describing the
        desired Clevis SSS (threshold) configuration for each LUKS device
    Args:
        butane_config (dict): A dictionary representing the parsed Butane YAML
    Returns:
        str: A JSON string  {"device": "/path/to/dev", "clevis": "{...json_config...}"}
    """

    def clevis_to_sss(clevis_config):
        """Returns a SSS config dict from a Clevis config dict"""
        pins = {}
        tang_configs = []
        # Clevis's default threshold is 1 if not specified
        threshold = clevis_config.get("threshold") or 1

        if clevis_config.get("tpm2"):
            # This is the standard default configuration for a tpm2 pin
            pins["tpm2"] = [{"hash": "sha256", "key": "ecc"}]

        for tang_server in clevis_config.get("tang") or []:
            if tang_server.get("url"):
                tang_configs.append({"url": tang_server["url"]})
            if tang_server.get("thumbprint"):
                tang_configs.append({"thp": tang_server["thumbprint"]})
            if tang_server.get("advertisement"):
                tang_configs.append({"advertisement": tang_server["advertisement"]})

        if tang_configs:
            pins["tang"] = tang_configs

        if not pins:
            # Only create a configuration if at least one pin is defined
            return None

        final_clevis_obj = {"t": threshold, "pins": pins}
        return final_clevis_obj

    storage_luks = []
    boot_device_luks = {}
    boot_device_processed = False
    root_device_path = None
    clevis_config_entries = {}

    if butane_config.get("storage") and butane_config["storage"].get("luks"):
        storage_luks = butane_config["storage"]["luks"]

    if butane_config.get("boot_device") and butane_config["boot_device"].get("luks"):
        boot_device_luks = butane_config["boot_device"]["luks"]

    for device in storage_luks:
        if device.get("name") == "root":
            root_device_path = device.get("device")
            break

    # Process the boot_device, associating it with the root path
    if boot_device_luks and (boot_device_luks.get("tpm2") or boot_device_luks.get("tang")):
        clevis_config = boot_device_luks
        device_path_to_use = (
            root_device_path if root_device_path else clevis_config.get("device")
        )

        if device_path_to_use:
            # Generate the Clevis SSS config for this device
            sss_config = clevis_to_sss(clevis_config)
            if sss_config:
                clevis_config_entries.update(
                    {"device": device_path_to_use, "clevis": sss_config}
                )
                boot_device_processed = True
        else:
            print(
                "WARNING: boot_device clevis config found but no device path could be determined for 'root'.",
                file=sys.stderr,
            )

    # Process other storage devices
    for device in storage_luks:
        if device.get("name") == "root" and boot_device_processed:
            continue

        clevis_config = device.get("clevis")
        device_path = device.get("device")
        if device_path and clevis_config:
            if clevis_config.get("custom"):
                print(
                    f"WARNING: Ignoring custom clevis setup in storage:luks:clevis for {device_path}: {clevis_config['custom']}",
                    file=sys.stderr,
                )
            else:
                # Generate the Clevis SSS config for this device
                sss_config = clevis_to_sss(clevis_config)
                if sss_config:
                    clevis_config_entries.update({"device": device_path, "clevis": sss_config})

    return json.dumps(clevis_config_entries)


class ButaneTranspiler(pulumi.ComponentResource):
    """Translate Jinja templated Butane files to Ignition and a subset to SaltStack Salt format

    renders credentials, butane_input, os/*.bu (excluding system_exclude) and basedir/**.bu

    Args:
    - resource_name (str): pulumi resource name
    - hostname (str): hostname
    - hostcert (pulumi object): host certificate
    - butane_input (str): Butane input string
    - basedir (str): Butane Basedir path
    - environment (dict, optional): env available in templating
        - defaults to `jinja_defaults.yml`
    - system_exclude (list, optional): list of files to exclude from translation.
    - opts (pulumi.ResourceOptions): Defaults to None

    Returns: pulumi.ComponentResource: ButaneTranspiler resource results
    - butane_config (Output[str]): The merged Butane YAML configuration
    - saltstack_config (Output[str]): The Butane translated to inlined SaltStack YAML
    - ignition_config (Output[str], Alias result): The Butane translated to Ignition JSON
    - this_env (Output.secret[dict)): Environment that was used for the translation
    - clevis_luks_config (Output[Str]): JSON config string of the clevis luks setup

    """

    def __init__(
        self,
        resource_name,
        hostname,
        hostcert,
        butane_input,
        basedir,
        environment=None,
        system_exclude=[],
        opts=None,
    ):
        from ..authority import ca_factory, acme_sub_ca, ssh_factory, ns_factory, config

        super().__init__(
            "pkg:os:ButaneTranspiler", "{}_butane".format(resource_name), None, opts
        )

        # create jinja environment
        default_env = yaml.safe_load(open(os.path.join(this_dir, "jinja_defaults.yml"), "r"))
        # add hostname from function call to environment
        default_env.update({"HOSTNAME": hostname})
        # add locale from config to environment
        default_env.update(
            {
                "LOCALE": {
                    key.upper(): value for key, value in config.get_object("locale").items()
                }
            }
        )

        # merge default with calling env
        this_env = merge_dict_struct(default_env, {} if environment is None else environment)

        # ssh and tls and other credstore related keys into butane type yaml
        # XXX also: /etc/local/ksk_anchor_internal.key
        butane_security_keys = pulumi.Output.concat(
            """
passwd:
  users:
    - name: core
      groups:
        - wheel
      ssh_authorized_keys:
""",
            ssh_factory.authorized_keys.apply(
                lambda x: "\n".join(["        - " + line for line in x.splitlines()])
            ),
            """
ignition:
  security:
    tls:
      certificate_authorities:
        - inline: |
""",
            ca_factory.root_bundle_pem.apply(
                lambda x: "\n".join(["            " + line for line in x.splitlines()])
            ),
            """
storage:
  files:
    - path: /etc/pki/ca-trust/source/anchors/root_bundle.crt
      mode: 0644
      contents:
        inline: |
""",
            ca_factory.root_bundle_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/pki/tls/certs/root_ca.crt
      mode: 0644
      contents:
        inline: |
""",
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/pki/tls/certs/server.crt
      mode: 0644
      contents:
        inline: |
""",
            hostcert.chain.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/pki/tls/private/server.key
      mode: 0600
      contents:
        inline: |
""",
            hostcert.key.private_key_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/acme_sub_ca.crt
      mode: 0644
      contents:
        inline: |
""",
            acme_sub_ca.chain.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/acme_sub_ca.key
      mode: 0600
      contents:
        inline: |
""",
            acme_sub_ca.key.private_key_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/ksk_internal.key
      mode: 0600
      contents:
        inline: |
""",
            ns_factory.ksk_key.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/local/ksk_anchor_bundle.key
      mode: 0644
      contents:
        inline: |
""",
            ns_factory.ksk_anchor_bundle.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/update_internal.key
      mode: 0600
      contents:
        inline: |
""",
            ns_factory.update_key.secret.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/acme_update_internal.key
      mode: 0600
      contents:
        inline: |
""",
            ns_factory.acme_update_key.secret.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/transfer_internal.key
      mode: 0600
      contents:
        inline: |
""",
            ns_factory.transfer_key.secret.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """
    - path: /etc/credstore/notify_internal.key
      mode: 0600
      contents:
        inline: |
""",
            ns_factory.notify_key.secret.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """

""",
        )

        # jinja template butane_input, basedir=basedir
        base_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_input, env=this_env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jinja template butane_security_keys, basedir=basedir
        security_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_security_keys, env=this_env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jinja template *.bu yaml files from os/ , exclude files from system_exclude
        system_dict = pulumi.Output.all(env=this_env).apply(
            lambda args: load_butane_dir(
                subproject_dir, args["env"], subdir="os", exclude=system_exclude
            )
        )

        # jinja template *.bu yaml files from basedir
        target_dict = pulumi.Output.all(env=this_env).apply(
            lambda args: load_butane_dir(basedir, args["env"])
        )

        # merged_dict= base_dict -> security_dict > target_dict -> system_dict
        merged_dict = pulumi.Output.all(
            base_dict=base_dict,
            security_dict=security_dict,
            system_dict=system_dict,
            target_dict=target_dict,
        ).apply(
            lambda args: merge_butane_dicts(
                args["system_dict"],
                merge_butane_dicts(
                    args["target_dict"],
                    merge_butane_dicts(args["security_dict"], args["base_dict"]),
                ),
            )
        )

        # convert butane merged_dict to butane yaml and export as butane_config
        self.butane_config = pulumi.Output.all(source_dict=merged_dict).apply(
            lambda args: yaml.safe_dump(args["source_dict"])
        )

        # create clevis_luks_config
        self.clevis_luks_config = pulumi.Output.all(butane_dict=merged_dict).apply(
            lambda args: butane_clevis_to_json_clevis(args["butane_dict"])
        )

        # create clevis_luks_update_sls
        if this_env["UPDATE_CLEVIS_LUKS_SLOTS"]:
            clevis_luks_config_json = pulumi.Output.all(
                clevis_dict=self.clevis_luks_config
            ).apply(lambda args: json.dumps(args["clevis_dict"]))
            this_env.update({"CLEVIS_LUKS_CONFIG": clevis_luks_config_json})

            clspy = jinja_run_file("os/clevis-luks-slots.py", subproject_dir, this_env)
            clevis_luks_update_sls = pulumi.Output.concat(
                """
clevis_luks_updater:
  file.managed:
    - name: /etc/local/update-clevis-luks-slots.py
    - contents: |
""",
                "".join([f"        {x}\n" for x in clspy.split("\n")]),
            )
        else:
            clevis_luks_update_sls = pulumi.Output.concat("")

        # make the used env for butane files processing available as secret
        self.this_env = pulumi.Output.secret(pulumi.Output.from_input(this_env))

        # additional service changed pattern list for butane_to_salt translation
        service_pattern_list = [
            r"/etc/local/(knot)/.*",
            r"/etc/unbound/(unbound).conf",
            r"/etc/(firewalld)/.*",
        ]

        # translate butane merged_dict to saltstack dict, convert to yaml,
        # append update-system-config.sls and basedir/*.sls, export as saltstack_config
        self.saltstack_config = pulumi.Output.concat(
            pulumi.Output.all(butane_dict=merged_dict).apply(
                lambda args: yaml.safe_dump(
                    butane_to_salt(
                        args["butane_dict"],
                        update_status=True,
                        update_dir=join_paths(
                            this_env["UPDATE_PATH"],
                            this_env["UPDATE_SERVICE"],
                        ),
                        update_user=this_env["UPDATE_UID"],
                        update_group=this_env["UPDATE_UID"],
                        extra_pattern_list=service_pattern_list,
                    )
                )
            ),
            clevis_luks_update_sls,
            open(os.path.join(this_dir, "update-system-config.sls"), "r").read(),
            *[open(f, "r").read() for f in glob.glob(os.path.join(basedir, "*.sls"))],
        )

        # translate merged butane yaml to ignition json config
        # XXX v0.19.0 Add -c/--check option to check config without producing output
        self.ignition_translation = command.local.Command(
            "{}_ignition_translation".format(resource_name),
            create="butane -d . -r -p",
            stdin=self.butane_config,
            dir=basedir,
            logging=LocalLogging.NONE,
            opts=pulumi.ResourceOptions(parent=self, additional_secret_outputs=["stdout"]),
        )
        # ignition json str as result
        self.ignition_config = self.ignition_translation.stdout
        self.result = self.ignition_config

        self.register_outputs({})


class SystemConfigUpdate(pulumi.ComponentResource):
    """reconfigure a remote system by executing salt-call on a butane to saltstack translated config

    if simulate==True: data is not transfered but written out to state/tmp/stack_name
    if simulate==None: simulate=pulumi.get_stack().endswith("sim")
    """

    def __init__(
        self,
        resource_name,
        host,
        system_config,
        simulate=None,
        opts=None,
    ):
        from ..tools import ssh_deploy, ssh_execute

        super().__init__(
            "pkg:os:SystemConfigUpdate",
            "{}_system_config_update".format(resource_name),
            None,
            opts,
        )

        child_opts = pulumi.ResourceOptions(parent=self)
        this_env = system_config.this_env

        user = this_env.apply(lambda env: env["UPDATE_USER"])
        update_fname = this_env.apply(lambda env: env["UPDATE_SERVICE"] + ".service")

        update_str_inputs = pulumi.Output.all(update_fname=update_fname, this_env=this_env)
        update_str = update_str_inputs.apply(
            lambda args: jinja_run_file(args["update_fname"], this_dir, args["this_env"])
        )

        root_dir = this_env.apply(
            lambda env_dict: join_paths(env_dict["UPDATE_PATH"], env_dict["UPDATE_SERVICE"])
        )
        source_inputs = pulumi.Output.all(root=root_dir, fname=update_fname)
        source = source_inputs.apply(lambda args: join_paths(args["root"], args["fname"]))

        target = update_fname.apply(lambda fname: join_paths("/etc/systemd/system", fname))
        sudo = this_env.apply(lambda env_dict: "sudo" if env_dict["UPDATE_USE_SUDO"] else "")

        cmdline_inputs = pulumi.Output.all(source=source, target=target, sudo=sudo)
        cmdline = cmdline_inputs.apply(
            lambda args: f"""if test -f {args["source"]}; then {args["sudo"]} cp {args["source"]} {args["target"]}; fi && \
                            {args["sudo"]} systemctl daemon-reload && \
                            {args["sudo"]} systemctl restart --wait update-system-config"""
        )

        # transport update service file content and main.sls (translated butane) to root_dir and sls_dir
        # XXX FIXME HARDCODED update filename and remote_prefix because we need to refactor ssh_deploy and others for dynamic filenames
        config_dict = {
            "update-system-config.service": update_str,
            "sls/main.sls": system_config.saltstack_config,
        }
        self.config_deployed = ssh_deploy(
            resource_name,
            host,
            user,
            files=config_dict,
            remote_prefix="/run/user/1000/update-system-config",
            simulate=simulate,
            opts=child_opts,
        )

        # copy update service to target location, reload systemd daemon, start update
        self.config_updated = ssh_execute(
            resource_name,
            host,
            user,
            cmdline=cmdline,
            simulate=simulate,
            triggers=self.config_deployed.triggers,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
        )

        self.result = self.config_updated
        self.register_outputs({})


class FcosImageDownloader(pulumi.ComponentResource):
    "download a version of fedora-coreos to local path, decompress, return filename"

    def __init__(
        self,
        stream=None,
        architecture=None,
        platform=None,
        image_format=None,
        overwrite_url=None,
        opts=None,
    ):
        from ..authority import project_dir, stack_name, config

        defaults = yaml.safe_load(
            open(os.path.join(this_dir, "..", "build_defaults.yml"), "r")
        )
        config = config.get_object("build")
        system_config = merge_dict_struct(defaults["fcos"], config.get("fcos") or {})

        if not stream:
            stream = system_config["stream"]
        if not architecture:
            architecture = system_config["architecture"]
        if not platform:
            platform = system_config["platform"]
        if not image_format:
            image_format = system_config["format"]

        resource_name = "system_{s}_{a}_{p}_{f}".format(
            s=stream, a=architecture, p=platform, f=image_format
        )
        if overwrite_url:
            resource_name = "system_{o}".format(o=os.path.basename(overwrite_url).strip(".xz"))

        super().__init__("pkg:os:FcosImageDownloader", resource_name, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        workdir = os.path.join(project_dir, "state", "tmp", stack_name, "fcos")
        os.makedirs(workdir, exist_ok=True)
        if overwrite_url:
            create_cmd = "coreos-installer download -C {w} -u {u} 2>/dev/null".format(
                w=workdir, u=overwrite_url
            )
        else:
            create_cmd = "coreos-installer download -s {s} -a {a} -p {p} -f {f} -C {w} 2>/dev/null".format(
                s=stream, a=architecture, p=platform, f=image_format, w=workdir
            )

        self.downloaded_image = command.local.Command(
            "download_{}".format(resource_name),
            create=create_cmd,
            dir=workdir,
            opts=child_opts,
        )

        self.decompressed_image = command.local.Command(
            "decompress_{}".format(resource_name),
            create=pulumi.Output.concat(
                'if test ! -e "$(echo ',
                self.downloaded_image.stdout,
                ' | sed -r "s/.xz$//")"; then xz --keep --decompress "',
                self.downloaded_image.stdout,
                '" 2>/dev/null; fi',
            ),
            dir=workdir,
            opts=child_opts,
        )

        self.fedora_version = self.downloaded_image.stdout.apply(
            lambda x: re.search(r"fedora-coreos-(\d+)\.", x).group(1)
            if re.search(r"fedora-coreos-(\d+)\.", x)
            else None
        )

        self.imagepath = self.downloaded_image.stdout.apply(lambda x: os.path.splitext(x)[0])
        self.result = self.imagepath
        self.register_outputs({})


class RemoteDownloadIgnitionConfig(pulumi.ComponentResource):
    def __init__(self, resource_name, hostname, remoteurl, opts=None):
        from ..authority import ca_factory

        super().__init__(
            "pkg:os:RemoteDownloadIgnitionConfig",
            "{}_remote_ignite".format(resource_name),
            None,
            opts,
        )

        this_opts = pulumi.ResourceOptions.merge(
            pulumi.ResourceOptions(parent=self, additional_secret_outputs=["stdout"]), opts
        )

        butane_remote_config = pulumi.Output.concat(
            """
variant: fcos
version: 1.6.0
ignition:
  config:
    replace:
      source: """,
            remoteurl,
            """
  security:
    tls:
      certificate_authorities:
        - inline: |        
""",
            ca_factory.root_bundle_pem.apply(
                lambda x: "\n".join(["            " + line for line in x.splitlines()])
            ),
            """
""",
        )

        ignition_remote_config = command.local.Command(
            "{}_ignition_remote_config".format(hostname),
            create="butane -d . -r -p",
            stdin=butane_remote_config,
            logging=LocalLogging.NONE,
            opts=this_opts,
        )

        self.result = ignition_remote_config.stdout
        self.register_outputs({})


class LibvirtIgniteFcos(pulumi.ComponentResource):
    """create a libvirt based x86_64 virtual machine according to an ignition config"""

    serial_tty_addon = """
      <serial type="pty">
        <target type="isa-serial" port="0">
          <model name="isa-serial"/>
        </target>
      </serial>
"""
    ignition_journal_addon = """
      <channel type="file">
        <target type="virtio" name="com.coreos.ignition.journal"/>
        <address type="virtio-serial"/>
        <source path="/tmp/test.out"/>
      </channel>
    """

    domain_additions_xslt = """
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template match="@* | node()">
    <xsl:copy>
      <xsl:apply-templates select="@* | node()"/>
    </xsl:copy>
  </xsl:template>
  <xsl:template match="/domain/devices">
    <xsl:copy>
      <xsl:apply-templates select="@* | node()"/>
{}
    </xsl:copy>
  </xsl:template>
</xsl:stylesheet>
""".format(serial_tty_addon)

    def __init__(
        self,
        resource_name,
        ignition_config,
        volumes=[{"name": "boot", "size": 8192, "device": "/dev/vda"}],
        memory=2048,
        vcpu=2,
        overwrite_url=None,
        opts=None,
    ):
        super().__init__(
            "pkg:os:LibvirtIgniteFcos",
            "{}_libvirt_ignite_fcos".format(resource_name),
            None,
            opts,
        )
        child_opts = pulumi.ResourceOptions(parent=self)

        # prepare ignite config for libvirt
        self.ignition = libvirt.Ignition(
            "{}_libvirt_ignition".format(resource_name),
            name="ignition",
            content=ignition_config,
            # XXX ignore changes to ignition_config, because saltstack is used for configuration updates
            opts=pulumi.ResourceOptions(parent=self, ignore_changes=["content"]),
        )

        # download qemu base image for libvirt, overwrite architecture, platform and image_format
        self.baseimage = FcosImageDownloader(
            architecture="x86_64",
            platform="qemu",
            image_format="qcow2.xz",
            overwrite_url=overwrite_url,
            opts=child_opts,
        )

        # create volumes, pass size if not boot vol, pass source if boot vol
        vm_volumes = []

        for entry in volumes:
            vm_vol = libvirt.Volume(
                "{}_vol_{}".format(resource_name, entry["name"]),
                pool="default",
                format="qcow2",
                source=self.baseimage.result if entry["name"] == "boot" else None,
                size=entry["size"] if entry["name"] != "boot" else None,
                opts=pulumi.ResourceOptions(parent=self, depends_on=[self.baseimage])
                if entry["name"] == "boot"
                else child_opts,
            )
            vm_volumes.append(vm_vol)
        self.volumes = vm_volumes

        # start domain with ignition config
        self.vm = libvirt.Domain(
            "{}_libvirt_vm".format(resource_name),
            memory=memory,
            vcpu=vcpu,
            coreos_ignition=self.ignition,
            disks=[libvirt.DomainDiskArgs(volume_id=vm_vol.id) for vm_vol in self.volumes],
            network_interfaces=[
                libvirt.DomainNetworkInterfaceArgs(network_name="default", wait_for_lease=True)
            ],
            qemu_agent=False,
            tpm=libvirt.DomainTpmArgs(backend_version="2.0", backend_persistent_state=True),
            xml=libvirt.DomainXmlArgs(xslt=self.domain_additions_xslt),
            opts=pulumi.ResourceOptions(
                parent=self,
                # ignore changes to ignition_config, because saltstack is used for configuration updates
                ignore_changes=["coreos_ignition"],
                # let creation take up to 5 minutes so coreos can update filetree to include guest agent for ip
                custom_timeouts=pulumi.CustomTimeouts(create="5m"),
            ),
        )
        self.result = self.vm
        self.register_outputs({})


class TangFingerprint(pulumi.ComponentResource):
    """connect and request fingerprint from a tang-server"""

    def __init__(self, tang_url, opts=None):
        super().__init__("pkg:os:TangFingerprint", tang_url, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        self.raw_print = purrl.Purrl(
            "raw_fingerprint",
            name="get_raw_fingerprint",
            method="GET",
            headers={},
            url=tang_url + "/adv",
            response_codes=["200"],
            opts=child_opts,
        )

        self.fingerprint = command.local.Command(
            "tang_fingerprint",
            create="jose fmt --json=- -g payload -y -o- | jose jwk use -i- -r -u verify -o- | jose jwk thp -i- -a S256",
            stdin=self.raw_print.response,
            opts=child_opts,
        )

        self.result = self.fingerprint.stdout
        self.register_outputs({})


class WaitForHostReady(pulumi.ComponentResource):
    """
    A Pulumi ComponentResource that waits for a remote host to be fully ready

    This component implements a robust, multi-stage wait logic for Fedora CoreOS,
    which needs to boot, provision (and layer packages), and then reboot.

    - **Connection Polling:** Actively polls for an SSH connection for configurable duration
    - **Command Polling:** Once connected, it runs a script that polls for a command to be available
    - **Reboot/Disconnect:** If the connection drops (e.g., FCOS reboots after rpm-ostree), the resource will fail
        Pulumi's engine will then retry the *entire* resource, which starts the connection polling again
    """

    def __init__(
        self,
        name: str,
        target: pulumi.Input[str],
        private_key: pulumi.Input[str],
        user: pulumi.Input[str] = "core",
        connection_timeout: str = "5m",
        connection_poll_interval_seconds: int = 10,
        command_poll_timeout_seconds: int = 300,
        command_poll_interval_seconds: int = 10,
        opts: pulumi.ResourceOptions = None,
    ):
        super().__init__("custom:resource:WaitForHostReady", name, {}, opts)

        # Options for the child resource, ensuring it's parented to this component
        child_opts = pulumi.ResourceOptions(parent=self)

        # 1. --- Connection Logic ---
        # This block handles your "try to connect for 5 minutes, every 10 seconds"
        # 'timeout' is the max duration.
        # 'dial_error_limit' is the number of "connection refused" retries.
        # We calculate the limit based on your desired poll interval.
        connection_retries = int(
            (int(connection_timeout.rstrip("m")) * 60) / connection_poll_interval_seconds
        )

        connection_args = pulumi_command.remote.ConnectionArgs(
            host=target,
            user=user,
            private_key=private_key,
            # Max time to wait for a successful connection.
            timeout=connection_timeout,
            # Retry connection errors this many times. This creates the
            # 10-second poll behavior you wanted.
            dial_error_limit=connection_retries,
        )

        # 2. --- Command Polling Logic ---
        # This script handles your "if connect but no knotc, wait 5 minutes"
        poll_attempts = command_poll_timeout_seconds // command_poll_interval_seconds

        poll_script = f"""
        bash -c "
        echo 'Successfully connected to host. Starting poll for knotc...';
        for i in $(seq 1 {poll_attempts}); do
            if which knotc; then
                echo 'SUCCESS: knotc found. Host is ready.';
                exit 0;
            fi;
            echo 'Waiting for knotc (rpm-ostree)... (Attempt $i/{poll_attempts})';
            sleep {command_poll_interval_seconds};
        done;
        echo 'FAILURE: Timed out after {command_poll_timeout_seconds}s waiting for knotc.';
        exit 1"
        """

        # 3. --- The 'remote.Command' Resource ---
        # This one resource handles both polling stages.
        # If it fails (connection drops, script exits 1), Pulumi's
        # engine will retry the *entire resource*, creating your outer loop.
        self.wait_command = pulumi_command.remote.Command(
            f"{name}-wait-script",
            connection=connection_args,
            # Run the same polling script for both create and update
            create=poll_script,
            update=poll_script,
            opts=child_opts,
        )

        # Register this component's outputs
        self.register_outputs(
            {
                "wait_command": self.wait_command,
            }
        )
