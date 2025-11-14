"""
## Pulumi - CoreOS Centric System Config, Deployment, Operation, Update

### Components

- ButaneTranspiler
- SystemConfigUpdate
- FcosImageDownloader
- LibvirtIgniteFcos
- TangFingerprint
- RemoteDownloadIgnitionConfig

### Functions

- get_locale
- build_raspberry_extras

"""

import glob
import os
import re
import sys
import json
import hashlib

import yaml
import pulumi
import pulumi_command as command
import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl
from pulumi_command.local import Logging as LocalLogging

from ..tools import log_warn, BuildFromSalt
from ..template import (
    jinja_run,
    jinja_run_file,
    load_butane_dir,
    butane_to_salt,
    join_paths,
    merge_dict_struct,
    merge_butane_dicts,
    butane_clevis_to_json_clevis,
)

this_dir = os.path.dirname(os.path.normpath(__file__))
subproject_dir = os.path.normpath(os.path.join(this_dir, ".."))
project_dir = os.getcwd()


def get_locale():
    """Retrieves and merges locale settings.

    This function reads the default locale settings from `jinja_defaults.yml`
    and merges them with any locale settings defined in the Pulumi
    configuration.

    Returns:
        dict:
            A dictionary of the merged locale settings.
    """
    from ..authority import config

    locale = yaml.safe_load(open(os.path.join(this_dir, "jinja_defaults.yml"), "r"))["LOCALE"]
    locale.update({key.upper(): value for key, value in config.get_object("locale").items()})
    return locale


def build_raspberry_extras():
    """Builds extra files for Raspberry Pi.

    This function triggers a SaltStack build to create extra files needed for
    Raspberry Pi devices, such as bootloader firmware.

    Returns:
        .result: A LocalSaltCall.result resource representing the Salt execution.
    """
    return BuildFromSalt(
        "build_raspberry_extras",
        sls_name="build_raspberry_extras",
        pillar=yaml.safe_load(open(os.path.join(this_dir, "build_raspberry_extras.yml"), "r")),
        environment={},
        sls_dir=this_dir,
        merge_config_name="",
    )


class ButaneTranspiler(pulumi.ComponentResource):
    """A Pulumi component for transpiling Butane configurations.

    This component processes Jinja2-templated Butane files, merges them, and
    transpiles the result into Ignition JSON and a SaltStack state.
    """

    def __init__(
        self,
        resource_name,
        hostname,
        hostcert,
        butane_input,
        basedir,
        environment=None,
        basedir_exclude=[os.path.basename(subproject_dir) + "/*"],
        system_exclude=[],
        opts=None,
    ):
        """Initializes a ButaneTranspiler component.

        Args:
            resource_name (str):
                The name of the resource.
            hostname (str):
                The hostname for the target system.
            hostcert (pulumi.Output):
                The host certificate for the target system.
            butane_input (str):
                The primary Butane configuration as a string.
            basedir (str):
                The base directory for resolving file paths.
            environment (dict, optional):
                A dictionary of environment variables for templating. Defaults to None.
            basedir_exclude (list[str], optional):
                A list of file patterns to exclude from the base directory. Defaults to
                excluding the subproject directory.
            system_exclude (list[str], optional):
                A list of file patterns to exclude from the system `os` directory.
                Defaults to [].
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.

        Returns:
            butane_config (Output[str]):
                The merged Butane YAML configuration.
            saltstack_config (Output[str]):
                The Butane translated to inlined SaltStack YAML.
            ignition_config (Output[str], Alias result):
                The Butane translated to Ignition JSON.
            this_env (Output.secret[dict]):
                Environment that was used for the translation.
            clevis_luks_config (Output[Str]):
                JSON config string of the clevis luks setup.
        """
        from ..authority import ca_factory, acme_sub_ca, ssh_factory, ns_factory, config

        super().__init__(
            "pkg:os:ButaneTranspiler", "{}_butane".format(resource_name), None, opts
        )

        # create jinja environment
        default_env = yaml.safe_load(open(os.path.join(this_dir, "jinja_defaults.yml"), "r"))
        # add hostname
        default_env.update({"HOSTNAME": hostname})
        # add locale
        default_env.update({"LOCALE": get_locale()})
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
            lambda args: load_butane_dir(
                basedir,
                args["env"],
                exclude=basedir_exclude,
                search_root=project_dir,
            )
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
            r"/etc/local/(frontend)/.*",
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

        # create sha256 hash of ignition_config
        self.ignition_config_hash = self.ignition_config.apply(
            lambda x: "sha256-{}".format(hashlib.sha256(x.encode("utf-8")).hexdigest())
        )
        self.result = self.ignition_config

        self.register_outputs({})


class SystemConfigUpdate(pulumi.ComponentResource):
    """A Pulumi component for updating the configuration of a remote system.

    This component uses a transpiled SaltStack state to reconfigure a remote
    system. It deploys the necessary configuration and triggers a Salt run.
    """

    def __init__(
        self,
        resource_name,
        host,
        system_config,
        simulate=None,
        opts=None,
    ):
        """Initializes a SystemConfigUpdate component.

        Args:
            resource_name (str):
                The name of the resource.
            host (pulumi.Input[str]):
                The hostname or IP address of the remote host.
            system_config (ButaneTranspiler):
                The transpiled system configuration.
            simulate (bool, optional):
                Whether to simulate the update. If None, it is determined by the stack name.
                Defaults to None.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        from ..tools import ssh_deploy, ssh_execute

        super().__init__(
            "pkg:os:SystemConfigUpdate",
            "{}_system_config_update".format(resource_name),
            None,
            opts,
        )

        stack_name = pulumi.get_stack()
        self.simulate = stack_name.endswith("sim") if simulate is None else simulate

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
            lambda args: f"""{args["sudo"]} cp {args["source"]} {args["target"]} && \
{args["sudo"]} systemctl daemon-reload && {args["sudo"]} systemctl restart --wait update-system-config"""
        )

        # transport update service file content and main.sls (translated butane) to root_dir and sls_dir
        config_dict = pulumi.Output.all(
            update_fname=update_fname,
            update_str=update_str,
            saltstack_config=system_config.saltstack_config,
        ).apply(
            lambda args: {
                args["update_fname"]: args["update_str"],
                "sls/main.sls": args["saltstack_config"],
            }
        )
        self.config_deployed = ssh_deploy(
            resource_name,
            host,
            user,
            files=config_dict,
            remote_prefix=root_dir,
            simulate=self.simulate,
            opts=child_opts,
        )

        # copy update service to target location, reload systemd daemon, start update
        self.config_updated = ssh_execute(
            resource_name,
            host,
            user,
            cmdline=cmdline,
            simulate=self.simulate,
            triggers=[self.config_deployed.deployment_hash],
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
        )

        self.result = self.config_updated
        self.register_outputs({})


class FcosImageDownloader(pulumi.ComponentResource):
    """A Pulumi component for downloading and decompressing a Fedora CoreOS image."""

    def __init__(
        self,
        stream=None,
        architecture=None,
        platform=None,
        image_format=None,
        overwrite_url=None,
        opts=None,
    ):
        """Initializes an FcosImageDownloader component.

        Args:
            stream (str, optional):         The Fedora CoreOS stream (e.g., "stable").
            architecture (str, optional):   The CPU architecture (e.g., "x86_64").
            platform (str, optional):       The platform (e.g., "qemu").
            image_format (str, optional):   The image format (e.g., "qcow2.xz").
            overwrite_url (str, optional):
                A URL to an image to download instead of using the stream/architecture/platform.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        Returns:
            self.result: ImagePath of generated image

        Defaults:
            Defaults are taken the merge of from "FCOS" section in `jinja_defaults.yml`,
            and optional pulumi config object settings `fcos`.

        """
        from ..authority import project_dir, stack_name, config

        defaults = yaml.safe_load(open(os.path.join(this_dir, "jinja_defaults.yml"), "r"))
        default_config = {key.upper(): value for key, value in defaults["FCOS"].items()}
        pulumi_config = {
            key.upper(): value for key, value in config.get_object("fcos").items()
        }
        system_config = merge_dict_struct(default_config, pulumi_config or {})

        if not stream:
            stream = system_config["STREAM"]
        if not architecture:
            architecture = system_config["ARCHITECTURE"]
        if not platform:
            platform = system_config["PLATFORM"]
        if not image_format:
            image_format = system_config["FORMAT"]

        resource_name = "system_{s}_{a}_{p}_{f}".format(
            s=stream, a=architecture, p=platform, f=image_format
        )
        if overwrite_url:
            resource_name = "system_{o}".format(o=os.path.basename(overwrite_url).strip(".xz"))

        super().__init__("pkg:os:FcosImageDownloader", resource_name, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        workdir = os.path.join(project_dir, "build", "tmp", stack_name, "fcos")
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
    """A Pulumi component for creating a remote Ignition configuration.

    This component generates a minimal Ignition configuration that downloads the
    full Ignition configuration from a remote URL.
    """

    def __init__(self, resource_name, hostname, remote_url, remote_hash="", opts=None):
        """Initializes a RemoteDownloadIgnitionConfig component.

        Args:
            resource_name (str):
                The name of the resource.
            hostname (str):
                The hostname for the target system.
            remote_url (pulumi.Input[str]):
                The URL to download the full Ignition configuration from.
            remote_hash (pulumi.Input[str]):
                The sha256 hash of the remote resource to download.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        from ..authority import ca_factory

        super().__init__(
            "pkg:os:RemoteDownloadIgnitionConfig",
            "{}_remote_ignite".format(resource_name),
            None,
            opts,
        )

        this_opts = pulumi.ResourceOptions.merge(
            pulumi.ResourceOptions(parent=self, additional_secret_outputs=["stdout"]),
            opts,
        )

        butane_hash_config = ""
        if remote_hash:
            butane_hash_config = pulumi.Output.concat(
                """
      http_headers:
        - name: "Verification-Hash"
          value: """,
                remote_hash,
                """
      verification:
        hash: """,
                remote_hash,
            )

        butane_remote_config = pulumi.Output.concat(
            """
variant: fcos
version: 1.6.0
ignition:
  config:
    replace:
      source: """,
            remote_url,
            """
""",
            butane_hash_config,
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

        self.ignition_config = command.local.Command(
            "{}_ignition_remote_config".format(hostname),
            create="butane -d . -r -p",
            stdin=butane_remote_config,
            logging=LocalLogging.NONE,
            opts=this_opts,
        )

        self.result = self.ignition_config.stdout
        self.register_outputs({})


class LibvirtIgniteFcos(pulumi.ComponentResource):
    """A Pulumi component for creating a Fedora CoreOS virtual machine with Libvirt."""

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
        """Initializes a LibvirtIgniteFcos component.

        Args:
            resource_name (str):
                The name of the resource.
            ignition_config (pulumi.Input[str]):
                The Ignition configuration in JSON format.
            volumes (list[dict], optional):
                A list of dictionaries defining the volumes for the VM. Defaults to a single
                8GB boot volume.
            memory (int, optional):
                The amount of memory for the VM in MB. Defaults to 2048.
            vcpu (int, optional):
                The number of virtual CPUs for the VM. Defaults to 2.
            overwrite_url (str, optional):
                A URL to an image to download instead of using the default Fedora CoreOS
                image. Defaults to None.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
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
    """A Pulumi component for retrieving a Tang server's fingerprint."""

    def __init__(self, tang_url, opts=None):
        """Initializes a TangFingerprint component.

        Args:
            tang_url (str):
                The URL of the Tang server.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
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
