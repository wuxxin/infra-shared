"""
## FCOS - Fedora-CoreOS

- updating, minimal, monolithic, container-focused operating system
- available for x86 and arm

### Components

- ButaneTranspiler
- FcosImageDownloader
- LibvirtIgniteFcos
- FcosConfigUpdate
- TangFingerprint
- RemoteDownloadIgnitionConfig

"""

import os
import copy
import json
import glob
import hashlib
import yaml

import pulumi
import pulumi_command as command
import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl

from ..tools import jinja_run, jinja_run_template, log_warn

this_dir = os.path.dirname(os.path.abspath(__file__))


class ButaneTranspiler(pulumi.ComponentResource):
    """transpile jinja templated butane files to ignition and a subset to saltstack salt format

    - jinja templating of butane yaml content with environment variables replacement
        - butane_input string with butane contents:local support from {basedir}
        - butane config for ssh keys, tls root_ca, server cert and key
        - {this_dir}/*.bu with **inlined** butane contents:local support from {this_dir}/..
        - {this_dir}/coreos-update-config.sls for migration helper from older fcos/*.bu
        - {basedir}/*.bu with butane contents:local support from {baserdir}
        - {basedir}/*.sls
    - returns
        - butane_config (merged butane yaml)
        - saltstack_config (merged butane transpiled to saltstack yaml with appended {basedir}/*.sls
        - ignition_config (merged butane to ignition json) -> result
    """

    def __init__(
        self, resource_name, hostname, hostcert, butane_input, basedir, env=None, opts=None
    ):
        from ..authority import ssh_factory, ca_factory

        super().__init__(
            "pkg:index:ButaneTranspiler", "{}_butane".format(resource_name), None, opts
        )
        child_opts = pulumi.ResourceOptions(parent=self)
        this_parent = os.path.abspath(os.path.join(this_dir, ".."))

        # configure hostname, ssh and tls keys into butane type yaml
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
                lambda x: "\n".join(["        - " + l for l in x.splitlines()])
            ),
            """
security:
  tls:
    certificate_authorities:
      - inline: |    
""",
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["          " + l for l in x.splitlines()])
            ),
            """
storage:
  files:
    - path: /etc/hostname
      mode: 0644
      contents:
        inline: """,
            hostname,
            """
    - path: /etc/ssl/certs/root_ca.crt
      filesystem: root
      mode: 0644
      contents:
        inline: |        
""",
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["          " + l for l in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/certs/server.crt
      filesystem: root
      mode: 0644
      contents:
        inline: |
""",
            hostcert.chain.apply(
                lambda x: "\n".join(["          " + l for l in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/private/server.key
      filesystem: root
      mode: 0600
      contents:
        inline: |
""",
            hostcert.key.private_key_pem.apply(
                lambda x: "\n".join(["          " + l for l in x.splitlines()])
            ),
            """

""",
        )

        # jinja template butane_input, basedir=basedir
        base_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_input, env=env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jina template butane_security_keys, basedir=basedir
        security_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_security_keys, env=env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jinja template *.bu yaml from this_dir, basedir=this_parent, inline all local references
        fcos_dict = pulumi.Output.all(
            loaded_yaml=self.load_yaml_files(this_parent, env)
        ).apply(lambda args: self.inline_local_files(args["loaded_yaml"], this_parent))

        # merge base_dict, security_dict, fcos_dict together
        merged_dict = pulumi.Output.all(base_dict, security_dict, fcos_dict).apply(
            lambda args: self.merge_yaml_struct(
                args[2], self.merge_yaml_struct(args[1], args[0])
            )
        )

        # jinja template *.bu yaml files from basedir, merge with merged_dict
        self.butane_config = pulumi.Output.all(
            loaded_yaml=self.load_yaml_files(basedir, env),
            base_yaml=merged_dict,
        ).apply(
            lambda args: yaml.safe_dump(
                self.merge_yaml_struct(args["loaded_yaml"], args["base_yaml"])
            )
        )
        # self.butane_config.apply(log_warn)

        # transpile merged butane yaml to saltstack salt yaml config
        # append this_dir/coreos-update-config.sls and basedir/*.sls to it
        self.jinja_transform = open(os.path.join(this_dir, "butane2salt.jinja"), "r").read()
        self.jinja_hash = hashlib.sha256(self.jinja_transform.encode("utf-8")).hexdigest()
        self.saltstack_config = pulumi.Output.concat(
            pulumi.Output.all(butane=self.butane_config).apply(
                lambda args: jinja_run(
                    self.jinja_transform,
                    basedir,
                    {"butane": yaml.safe_load(args["butane"]), "jinja_hash": self.jinja_hash},
                )
            ),
            open(os.path.join(this_dir, "coreos-update-config.sls"), "r").read(),
            *[open(f, "r").read() for f in glob.glob(os.path.join(this_dir, "*.sls"))],
        )

        # transpile merged butane yaml to ignition json config
        # XXX due to pulumi-command exit 1 on stderr output, we silence stderr,
        #   but output is vital for finding compilation warning and errors, so remove 2>/dev/null on debug
        self.ignition_config = command.local.Command(
            "{}_ignition_config".format(resource_name),
            create="butane -d . -r -p 2>/dev/null",
            stdin=self.butane_config,
            dir=basedir,
            opts=child_opts,
        )

        self.result = self.ignition_config.stdout
        self.register_outputs({})

    def inline_local_files(self, yaml_dict, basedir):
        """inline the contents of butane local references in the yaml for
        - storage:files:contents:local
        - systemd:units:contents_local
        - systemd:units:dropins:contents_local"""

        def read_include(basedir, filename):
            return open(os.path.join(basedir, filename), "r").read()

        ydict = copy.deepcopy(yaml_dict)

        if "storage" in ydict and "files" in ydict["storage"]:
            for fnr in range(len(ydict["storage"]["files"])):
                f = ydict["storage"]["files"][fnr]

                if "contents" in f and "local" in f["contents"]:
                    fname = f["contents"]["local"]
                    del ydict["storage"]["files"][fnr]["contents"]["local"]
                    ydict["storage"]["files"][fnr]["contents"].update(
                        {"inline": read_include(basedir, fname)}
                    )

        if "systemd" in ydict and "units" in ydict["systemd"]:
            for unr in range(len(ydict["systemd"]["units"])):
                u = ydict["systemd"]["units"][unr]

                if "contents_local" in u:
                    fname = u["contents_local"]
                    del ydict["systemd"]["units"][unr]["contents_local"]
                    ydict["systemd"]["units"][unr].update(
                        {"contents": read_include(basedir, fname)}
                    )

                if "dropins" in u:
                    for dnr in range(len(u["dropins"])):
                        d = ydict["systemd"]["units"][unr]["dropins"][dnr]

                        if "contents_local" in d:
                            fname = d["contents_local"]
                            del ydict["systemd"]["units"][unr]["dropins"][dnr][
                                "contents_local"
                            ]
                            ydict["systemd"]["units"][unr]["dropins"][dnr].update(
                                {"contents": read_include(basedir, fname)}
                            )
        return ydict

    def load_yaml_files(self, basedir, env):
        """get a list of all *.bu files from the basedir,
        sorted with the files from the basedir first, then all subdirs
        read the corresponding files with jinja templating, parse as yaml, merge together
        """

        all_files = sorted(
            [
                os.path.relpath(fname, basedir)
                for fname in glob.glob(os.path.join(basedir, "*.bu"))
            ]
            + [
                os.path.relpath(fname, basedir)
                for fname in glob.glob(os.path.join(basedir, "**", "*.bu"), recursive=True)
            ]
        )

        merged_yaml = {}
        for fname in all_files:
            yaml_dict = pulumi.Output.all(fname=fname, env=env).apply(
                lambda args: yaml.safe_load(
                    jinja_run_template(args["fname"], basedir, args["env"])
                )
            )
            merged_yaml = pulumi.Output.all(
                yaml1_dict=merged_yaml, yaml2_dict=yaml_dict
            ).apply(
                lambda args: self.merge_yaml_struct(args["yaml1_dict"], args["yaml2_dict"])
            )
        return merged_yaml

    def merge_yaml_struct(self, yaml1, yaml2):
        "merge struct yaml1 and yaml2 together"

        def is_dict_like(v):
            return hasattr(v, "keys") and hasattr(v, "values") and hasattr(v, "items")

        def is_list_like(v):
            return hasattr(v, "append") and hasattr(v, "extend") and hasattr(v, "pop")

        ymerge = copy.deepcopy(yaml1)
        if is_dict_like(yaml1) and is_dict_like(yaml2):
            for key in yaml2:
                if key in yaml1:
                    # if the key is present in both dictionaries, recursively merge the values
                    ymerge[key] = self.merge_yaml_struct(yaml1[key], yaml2[key])
                else:
                    ymerge[key] = yaml2[key]
        elif is_list_like(yaml1) and is_list_like(yaml2):
            for item in yaml2:
                if item not in yaml1:
                    ymerge.append(item)
        else:
            # if neither input is a dictionary or list, the second input overwrites the first input
            ymerge = yaml2
        return ymerge


class FcosImageDownloader(pulumi.ComponentResource):
    "download a version of fedora-coreos to local path, decompress, return filename"

    def __init__(self, stream=None, architecture=None, platform=None, format=None, opts=None):
        from ..authority import project_dir, stack_name

        defaults = yaml.safe_load(open(os.path.join(this_dir, "..", "defaults.yml"), "r"))

        if not stream:
            stream = defaults["fcos"]["stream"]
        if not architecture:
            architecture = defaults["fcos"]["architecture"]
        if not platform:
            platform = defaults["fcos"]["platform"]
        if not format:
            format = defaults["fcos"]["format"]

        resource_name = "fcos_{s}_{a}_{p}_{f}".format(
            s=stream, a=architecture, p=platform, f=format
        )

        super().__init__("pkg:index:FcosImageDownloader", resource_name, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        workdir = os.path.join(project_dir, "state", "tmp", stack_name, "fcos")
        os.makedirs(workdir, exist_ok=True)

        self.downloaded_image = command.local.Command(
            "download_{}".format(resource_name),
            create="coreos-installer download -s {s} -a {a} -p {p} -f {f} -C {w} 2>/dev/null".format(
                s=stream, a=architecture, p=platform, f=format, w=workdir
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
        self.imagepath = self.downloaded_image.stdout.apply(lambda x: os.path.splitext(x)[0])
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
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["            " + l for l in x.splitlines()])
            ),
            """
""",
        )

        ignition_remote_config = command.local.Command(
            "{}_ignition_remote_config".format(hostname),
            create="butane -d . -r -p",
            stdin=butane_remote_config,
            opts=pulumi.ResourceOptions(additional_secret_outputs=["stdout"], parent=self),
        )

        self.result = ignition_remote_config.stdout
        self.register_outputs({})


class LibvirtIgniteFcos(pulumi.ComponentResource):
    """create a libvirt based virtual machine according to an ignition config"""

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
""".format(
        serial_tty_addon
    )

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
            # XXX ignore changes to ignition_configm, because saltstack is used for configuration updates
            opts=pulumi.ResourceOptions(parent=self, ignore_changes=["content"]),
        )

        # download qemu base image
        self.baseimage = FcosImageDownloader(
            platform="qemu", format="qcow2.xz", opts=child_opts
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
            qemu_agent=True,
            tpm=libvirt.DomainTpmArgs(backend_version="2.0", backend_persistent_state=True),
            xml=libvirt.DomainXmlArgs(xslt=self.domain_additions_xslt),
            # XXX ignore changes to ignition_configm, because saltstack is used for configuration updates
            opts=pulumi.ResourceOptions(parent=self, ignore_changes=["coreos_ignition"]),
        )
        self.result = self.vm
        self.register_outputs({})


class FcosConfigUpdate(pulumi.ComponentResource):
    def __init__(self, resource_name, host, salt, pillar={}, opts=None):
        from ..tools import RemoteSaltCall

        super().__init__(
            "pkg:index:FcosConfigUpdate",
            "{}_fcos_config_update".format(resource_name),
            None,
            opts,
        )
        child_opts = pulumi.ResourceOptions(parent=self)
        base_dir = "/run/user/1000"
        root_dir = os.path.join(base_dir, "coreos-update-config")

        self.host_update = RemoteSaltCall(
            "{}_config_update_deploy".format(resource_name),
            host,
            "core",
            base_dir,
            pillar=pillar,
            salt=salt,
            exec="sudo systemctl restart --wait coreos-update-config",
            root_dir=root_dir,
            tmp_dir=os.path.join(root_dir, "tmp"),
            sls_dir=os.path.join(root_dir, "sls"),
            opts=child_opts,
        )
        self.result = self.host_update
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
