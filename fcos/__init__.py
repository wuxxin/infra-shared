"""
## Pulumi - Fedora CoreOS

### Components

- ButaneTranspiler
- FcosConfigUpdate
- FcosImageDownloader
- LibvirtIgniteFcos
- TangFingerprint
- RemoteDownloadIgnitionConfig

"""

import glob
import os
import re

import pulumi
import pulumi_command as command
import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl
import yaml

from ..tools import log_warn
from ..template import (
    jinja_run,
    jinja_run_file,
    join_paths,
    merge_dict_struct,
    merge_butane_dicts,
    load_butane_dir,
    butane_to_salt,
)

this_dir = os.path.dirname(os.path.abspath(__file__))
subproject_dir = os.path.abspath(os.path.join(this_dir, ".."))


class ButaneTranspiler(pulumi.ComponentResource):
    """translate jinja templated butane files to ignition and a subset to saltstack salt format

    - uses `jinja_defaults.yml` for environment defaults available in jinja
    - returns
        - butane_config (merged butane yaml)
        - saltstack_config (butane translated to inlined saltstack yaml with customizations
        - ignition_config (butane translated to ignition json) -> result
    """

    def __init__(
        self,
        resource_name,
        hostname,
        hostcert,
        butane_input,
        basedir,
        environment=None,
        opts=None,
    ):
        from ..authority import ca_factory, ssh_factory

        super().__init__(
            "pkg:index:ButaneTranspiler", "{}_butane".format(resource_name), None, opts
        )

        # create jinja environment
        default_env = yaml.safe_load(
            open(os.path.join(this_dir, "jinja_defaults.yml"), "r")
        )
        # add hostname from function call to environment
        default_env.update({"HOSTNAME": hostname})

        # merge default with calling env
        this_env = merge_dict_struct(
            default_env, {} if environment is None else environment
        )

        # ssh and tls keys into butane type yaml
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
    - path: /etc/ssl/certs/root_bundle.crt
      mode: 0644
      contents:
        inline: |
""",
            ca_factory.root_bundle_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/certs/root_ca.crt
      mode: 0644
      contents:
        inline: |
""",
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/certs/server.crt
      mode: 0644
      contents:
        inline: |
""",
            hostcert.chain.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/private/server.key
      mode: 0600
      contents:
        inline: |
""",
            hostcert.key.private_key_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """

""",
        )

        # jinja template butane_input, basedir=basedir
        base_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_input, env=this_env).apply(
                lambda args: yaml.safe_load(
                    jinja_run(args["yaml_str"], basedir, args["env"])
                )
            )
        )

        # jinja template butane_security_keys, basedir=basedir
        security_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_security_keys, env=this_env).apply(
                lambda args: yaml.safe_load(
                    jinja_run(args["yaml_str"], basedir, args["env"])
                )
            )
        )

        # jinja template *.bu yaml files from fcosdir
        fcos_dict = pulumi.Output.all(env=this_env).apply(
            lambda args: load_butane_dir(subproject_dir, args["env"], subdir="fcos")
        )

        # jinja template *.bu yaml files from basedir
        target_dict = pulumi.Output.all(env=this_env).apply(
            lambda args: load_butane_dir(basedir, args["env"])
        )

        # merged_dict= base_dict -> security_dict > target_dict -> fcos_dict
        merged_dict = pulumi.Output.all(
            base_dict=base_dict,
            security_dict=security_dict,
            fcos_dict=fcos_dict,
            target_dict=target_dict,
        ).apply(
            lambda args: merge_butane_dicts(
                args["fcos_dict"],
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
        # self.butane_config.apply(log_warn)

        # translate butane merged_dict to saltstack dict, convert to yaml,
        # append update-system-config.sls and basedir/*.sls, export as saltstack_config
        self.saltstack_config = pulumi.Output.concat(
            pulumi.Output.all(butane_dict=merged_dict).apply(
                lambda args: yaml.safe_dump(
                    butane_to_salt(
                        args["butane_dict"],
                        update_status=True,
                        update_dir="/run/user/1000/update-system-config",
                        update_user=1000,
                        update_group=1000,
                    )
                )
            ),
            open(os.path.join(this_dir, "update-system-config.sls"), "r").read(),
            *[open(f, "r").read() for f in glob.glob(os.path.join(basedir, "*.sls"))],
        )

        # translate merged butane yaml to ignition json config
        # XXX v0.19.0 Add -c/--check option to check config without producing output
        self.ignition_config = command.local.Command(
            "{}_ignition_config".format(resource_name),
            create="butane -d . -r -p",
            stdin=self.butane_config,
            dir=basedir,
            opts=pulumi.ResourceOptions(
                parent=self, additional_secret_outputs=["stdout"]
            ),
        )

        # export used env
        self.this_env = pulumi.Output.secret(pulumi.Output.from_input(this_env))

        # alias ignition json as result
        self.result = self.ignition_config.stdout
        self.register_outputs({})


class FcosConfigUpdate(pulumi.ComponentResource):
    """reconfigure a remote CoreOS System by executing salt-call on a butane to saltstack translated config"""

    def __init__(self, resource_name, host, compiled_config, opts=None):
        from ..tools import ssh_deploy, ssh_execute

        super().__init__(
            "pkg:index:FcosConfigUpdate",
            "{}_fcos_config_update".format(resource_name),
            None,
            opts,
        )

        child_opts = pulumi.ResourceOptions(parent=self)
        user = "core"
        update_fname = "update-system-config.service"
        update_str = open(join_paths(this_dir, update_fname), "r").read()
        root_dir = join_paths("/run/user/1000", "update-system-config")

        # transport update service file content and main.sls (translated butane) to root_dir and sls_dir
        config_dict = {
            update_fname: pulumi.Output.from_input(update_str),
            os.path.join("sls", "main.sls"): pulumi.Output.from_input(
                compiled_config.saltstack_config
            ),
        }
        self.config_deployed = ssh_deploy(
            resource_name,
            host,
            user,
            files=config_dict,
            remote_prefix=root_dir,
            simulate=False,
            opts=child_opts,
        )

        # copy update service to target location, reload systemd daemon, start update
        self.config_updated = ssh_execute(
            resource_name,
            host,
            user,
            cmdline="""if test -f {source}; then sudo cp {source} {target}; fi && \
                        sudo systemctl daemon-reload && \
                        sudo systemctl restart --wait update-system-config""".format(
                source=os.path.join(root_dir, update_fname),
                target=os.path.join("/etc/systemd/system", update_fname),
            ),
            simulate=False,
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
        opts=None,
    ):
        from ..authority import project_dir, stack_name, config

        defaults = yaml.safe_load(
            open(os.path.join(this_dir, "..", "build_defaults.yml"), "r")
        )

        config = config.get_object("build")
        fcos_config = merge_dict_struct(defaults["fcos"], config.get("fcos", {}))

        if not stream:
            stream = fcos_config["stream"]
        if not architecture:
            architecture = fcos_config["architecture"]
        if not platform:
            platform = fcos_config["platform"]
        if not image_format:
            image_format = fcos_config["format"]

        resource_name = "fcos_{s}_{a}_{p}_{f}".format(
            s=stream, a=architecture, p=platform, f=image_format
        )

        super().__init__("pkg:index:FcosImageDownloader", resource_name, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        workdir = os.path.join(project_dir, "state", "tmp", stack_name, "fcos")
        os.makedirs(workdir, exist_ok=True)

        self.downloaded_image = command.local.Command(
            "download_{}".format(resource_name),
            create="coreos-installer download -s {s} -a {a} -p {p} -f {f} -C {w} 2>/dev/null".format(
                s=stream, a=architecture, p=platform, f=image_format, w=workdir
            ),
            dir=workdir,
            opts=child_opts,
        )

        self.decompressed_image = command.local.Command(
            "decompress_{}".format(resource_name),
            create=pulumi.Output.format(
                'if test ! -e "$(echo {f} | sed -r "s/.xz$//")"; then xz --keep --decompress "{f}" 2>/dev/null; fi',
                f=self.downloaded_image.stdout,
            ),
            dir=workdir,
            opts=child_opts,
        )

        self.fedora_version = self.downloaded_image.stdout.apply(
            lambda x: re.search(r"fedora-coreos-(\d+)\.", x).group(1)
            if re.search(r"fedora-coreos-(\d+)\.", x)
            else None
        )

        self.imagepath = self.downloaded_image.stdout.apply(
            lambda x: os.path.splitext(x)[0]
        )
        self.result = self.imagepath
        self.register_outputs({})


class RemoteDownloadIgnitionConfig(pulumi.ComponentResource):
    def __init__(self, resource_name, hostname, remoteurl, opts=None):
        from ..authority import ca_factory

        super().__init__(
            "pkg:index:RemoteDownloadIgnitionConfig",
            "{}_remote_ignite".format(resource_name),
            None,
            opts,
        )

        butane_remote_config = pulumi.Output.concat(
            """
variant: fcos
version: 1.5.0
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
            opts=pulumi.ResourceOptions(
                additional_secret_outputs=["stdout"], parent=self
            ),
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
        opts=None,
    ):
        super().__init__(
            "pkg:index:LibvirtIgniteFcos",
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
            disks=[
                libvirt.DomainDiskArgs(volume_id=vm_vol.id) for vm_vol in self.volumes
            ],
            network_interfaces=[
                libvirt.DomainNetworkInterfaceArgs(
                    network_name="default", wait_for_lease=True
                )
            ],
            qemu_agent=False,
            tpm=libvirt.DomainTpmArgs(
                backend_version="2.0", backend_persistent_state=True
            ),
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
        super().__init__("pkg:index:TangFingerprint", tang_url, None, opts)
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
