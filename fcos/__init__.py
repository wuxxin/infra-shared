"""
## Pulumi - Fedora CoreOS

- updating, minimal, monolithic, container-focused operating system
- available for x86 and arm

### Library Features

- Jinja templating of butane yaml content with environment variables replacement
- Configuration and Initial Boot
    - authorized_keys, tls cert, key, ca_cert, loads container secrets
    - install ostree or var/local/bin extensions
- Reconfiguration / Update Configuration using translated butane to salt
- Comfortable Deployment of
    - Single Container: `podman-systemd.unit` - run systemd container units using podman-quadlet
    - Compose Container: `compose.yml` - run multi-container applications defined using a compose file
    - nSpawn OS-Container: `systemd-nspawn` - run an linux OS (build by mkosi) in a light-weight container

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
import stat
import json
import glob
import yaml

import pulumi
import pulumi_command as command
import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl

from ..tools import jinja_run, jinja_run_template, merge_dict_struct, log_warn

this_dir = os.path.dirname(os.path.abspath(__file__))


class ButaneTranspiler(pulumi.ComponentResource):
    """translate jinja templated butane files to ignition and a subset to saltstack salt format

    - environment available in jinja with defaults for
        - Boolean DEBUG
        - Dict LOCALE: {LANG,KEYMAP,TIMEZONE}
        - List RPM_OSTREE_INSTALL
    - jinja butane templating
        - override order: butane_input -> butane_security -> this_dir*.bu -> basedir/*.bu
        - butane_input string with butane contents:local support from {basedir}
        - butane_security config for hostname, ssh keys, tls root_ca, server cert and key
        - {this_dir}/*.bu with **inlined** butane contents:local support from {this_dir}/..
        - {basedir}/*.bu with butane contents:local support from {basedir}
    - saltstack translation
        - jinja templating of butane2salt.jinja with butane_config as environment
        - {this_dir}/coreos-update-config.sls for migration helper from older fcos/*.bu
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

        default_env_str = """
DEBUG: false
RPM_OSTREE_INSTALL:
  - mkosi
LOCALE:
  LANG: en_US.UTF-8
  KEYMAP: us
  TIMEZONE: UTC
  COUNTRY_CODE: UN
"""
        default_env = yaml.safe_load(default_env_str)
        this_env = merge_dict_struct(default_env, {} if env is None else env)

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
            pulumi.Output.all(yaml_str=butane_input, env=this_env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jina template butane_security_keys, basedir=basedir
        security_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_security_keys, env=this_env).apply(
                lambda args: yaml.safe_load(jinja_run(args["yaml_str"], basedir, args["env"]))
            )
        )

        # jinja template *.bu yaml from this_dir, basedir=this_parent
        # inline all local references, inline storage:trees as storage:files
        fcos_dict = pulumi.Output.all(
            loaded_yaml=self.load_butane_files(this_parent, env=this_env)
        ).apply(
            lambda args: self.inline_local_files(
                args["loaded_yaml"], this_parent, include_trees=True
            )
        )

        # jinja template *.bu yaml files from basedir
        # merge base_dict -> security_dict > loaded_dict -> fcos_dict
        self.butane_config = pulumi.Output.all(
            base_dict=base_dict,
            security_dict=security_dict,
            fcos_dict=fcos_dict,
            loaded_yaml=self.load_butane_files(basedir, env=this_env),
        ).apply(
            lambda args: yaml.safe_dump(
                merge_dict_struct(
                    args["fcos_dict"],
                    merge_dict_struct(
                        args["loaded_yaml"],
                        merge_dict_struct(args["security_dict"], args["base_dict"]),
                    ),
                )
            )
        )

        # translate merged butane yaml to saltstack salt yaml config
        # append this_dir/coreos-update-config.sls and basedir/*.sls to it
        self.saltstack_config = pulumi.Output.concat(
            pulumi.Output.all(butane=self.butane_config).apply(
                lambda args: jinja_run_template(
                    "butane2salt.jinja",
                    [basedir, this_dir],
                    {"butane": yaml.safe_load(args["butane"])},
                )
            ),
            open(os.path.join(this_dir, "coreos-update-config.sls"), "r").read(),
            *[open(f, "r").read() for f in glob.glob(os.path.join(basedir, "*.sls"))],
        )

        # self.butane_config.apply(log_warn)

        # translate merged butane yaml to ignition json config
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

    def inline_local_files(self, yaml_dict, basedir, include_trees=False):
        """inline the contents of butane local references

        - storage:files:contents:local
        - systemd:units:contents_local
        - systemd:units:dropins:contents_local
        - storage:trees (if include_trees is True)

        """

        def join_paths(basedir, *filepaths):
            filepaths = [path[1:] if path.startswith("/") else path for path in filepaths]
            return os.path.join(basedir, *filepaths)

        def read_include(basedir, *filepaths):
            return open(join_paths(basedir, *filepaths), "r").read()

        ydict = copy.deepcopy(yaml_dict)

        if include_trees and "storage" in ydict and "trees" in ydict["storage"]:
            for tnr in range(len(ydict["storage"]["trees"])):
                t = ydict["storage"]["trees"][tnr]
                for f in glob.glob(
                    "**",
                    root_dir=join_paths(basedir, t["local"]),
                    recursive=True,
                ):
                    lf = join_paths(basedir, t["local"], f)
                    if not os.path.isdir(lf):
                        rf = join_paths(t["path"] if "path" in t else "/", f)
                        is_exec = os.stat(lf).st_mode & stat.S_IXUSR
                        ydict["storage"]["files"].append(
                            {
                                "path": rf,
                                "mode": 0o755 if is_exec else 0o664,
                                "contents": {"inline": read_include(lf)},
                            }
                        )
            del ydict["storage"]["trees"]

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

    def load_butane_files(self, basedir, env):
        """read and jinja template all *.bu files from basedir recursive, parse as yaml, merge together"""

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
            ).apply(lambda args: merge_dict_struct(args["yaml1_dict"], args["yaml2_dict"]))
        return merged_yaml


class FcosImageDownloader(pulumi.ComponentResource):
    "download a version of fedora-coreos to local path, decompress, return filename"

    def __init__(self, stream=None, architecture=None, platform=None, format=None, opts=None):
        from ..authority import project_dir, stack_name

        defaults = yaml.safe_load(
            open(os.path.join(this_dir, "..", "build_defaults.yml"), "r")
        )

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
            # XXX ignore changes to ignition_config, because saltstack is used for configuration updates
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
            # XXX ignore changes to ignition_config, because saltstack is used for configuration updates
            opts=pulumi.ResourceOptions(parent=self, ignore_changes=["coreos_ignition"]),
        )
        self.result = self.vm
        self.register_outputs({})


class FcosConfigUpdate(pulumi.ComponentResource):
    """reconfigure a remote CoreOS System by executing salt-call on a butane to saltstack translated config

    Modifications to *.bu and their referenced files will result in a new saltstack config

    - Copies a systemd.service and a main.sls state file to the remote target in a /run directory
    - overwrite original update service, reload systemd, start service, configures a salt environment
    - execute main.sls in an saltstack container where /etc, /var, /run is mounted from the host
    - only the butane sections: storage:[directories,files,links,trees] systemd:unit[:dropins] are translated
    - additional migration code can be written in basedir/*.sls
        - use for adding saltstack migration code to cleanup after updates, eg. deleting files and services

    - advantages of this approach
        - it can update from a broken version of itself
        - compared to plain a shell script because its a systemd service
            - it is independent of the shell, doesn't die on disconnect, has logs

    """

    def __init__(self, resource_name, host, transpiled_butane, opts=None):
        from ..tools import ssh_execute, ssh_deploy

        super().__init__(
            "pkg:index:FcosConfigUpdate",
            "{}_fcos_config_update".format(resource_name),
            None,
            opts,
        )

        child_opts = pulumi.ResourceOptions(parent=self)
        user = "core"
        root_dir = "/run/user/1000/coreos-update-config"
        sls_dir = os.path.join(root_dir, "sls")
        update_fname = "coreos-update-config.service"
        update_str = open(os.path.join(this_dir, update_fname), "r").read()

        # transport update service file and main.sls (translated butane) to root_dir and sls_dir
        config_dict = {
            os.path.join(root_dir, update_fname): pulumi.Output.from_input(update_str),
            os.path.join(sls_dir, "main.sls"): pulumi.Output.from_input(
                transpiled_butane.saltstack_config
            ),
        }

        # copy update service to target location, reload systemd daemon, start update
        cmdline = """sudo cp {source} {target} && sudo systemctl daemon-reload && \
                        sudo systemctl restart --wait coreos-update-config""".format(
            source=os.path.join(root_dir, update_fname),
            target=os.path.join("/etc/systemd/system", update_fname),
        )

        self.config_deployed = ssh_deploy(
            resource_name, host, user, files=config_dict, simulate=False, opts=child_opts
        )

        self.coreos_update_config = ssh_execute(
            resource_name,
            host,
            user,
            cmdline=cmdline,
            simulate=False,
            triggers=self.config_deployed.triggers,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
        )

        self.result = self.coreos_update_config
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
