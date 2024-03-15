"""
## Pulumi - Fedora CoreOS

### Components

- ButaneTranspiler
- FcosImageDownloader
- LibvirtIgniteFcos
- FcosConfigUpdate
- TangFingerprint
- RemoteDownloadIgnitionConfig

### Python Functions
- compile_selinux_module

"""

import base64
import copy
import glob
import os
import re
import stat
import subprocess

import pulumi
import pulumi_command as command
import pulumi_libvirt as libvirt
import pulumiverse_purrl as purrl
import yaml

from ..template import jinja_run, jinja_run_template, join_paths, merge_dict_struct

this_dir = os.path.dirname(os.path.abspath(__file__))
subproject_dir = os.path.abspath(os.path.join(this_dir, ".."))

# default template environment, if nothing else is defined
DEFAULT_ENV_STR = """
DEBUG: false
UPDATE_SERVICE_STATUS: true
CONTAINER_FRONTEND: true
DNS_RESOLVER: true
RESIDENT_CIDR: 10.140.250.1/24
RPM_OSTREE_INSTALL:
  - docker-compose
  - podman-compose
  - systemd-networkd
LOCALE:
  LANG: en_US.UTF-8
  KEYMAP: us
  TIMEZONE: UTC
  COUNTRY_CODE: UN
"""


class ButaneTranspiler(pulumi.ComponentResource):
    """translate jinja templated butane files to ignition and a subset to saltstack salt format

    - see DEFAULT_ENV_STR for environment defaults available in jinja
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

        default_env = yaml.safe_load(DEFAULT_ENV_STR)
        this_env = merge_dict_struct(
            default_env, {} if environment is None else environment
        )

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
                lambda x: "\n".join(["        - " + line for line in x.splitlines()])
            ),
            """
security:
  tls:
    certificate_authorities:
      - inline: |    
""",
            ca_factory.root_cert_pem.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
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
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/certs/server.crt
      filesystem: root
      mode: 0644
      contents:
        inline: |
""",
            hostcert.chain.apply(
                lambda x: "\n".join(["          " + line for line in x.splitlines()])
            ),
            """          
    - path: /etc/ssl/private/server.key
      filesystem: root
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

        # 1. jinja template butane_input, basedir=basedir
        base_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_input, env=this_env).apply(
                lambda args: yaml.safe_load(
                    jinja_run(args["yaml_str"], basedir, args["env"])
                )
            )
        )

        # 2. jina template butane_security_keys, basedir=basedir
        security_dict = pulumi.Output.secret(
            pulumi.Output.all(yaml_str=butane_security_keys, env=this_env).apply(
                lambda args: yaml.safe_load(
                    jinja_run(args["yaml_str"], basedir, args["env"])
                )
            )
        )

        # 3. jinja template *.bu yaml from fcosdir and inline all local references
        fcos_dict = pulumi.Output.all(
            loaded_dict=self.load_butane_files(subproject_dir, this_env, subdir="fcos")
        ).apply(
            lambda args: self.inline_local_files(subproject_dir, args["loaded_dict"])
        )

        # 4. jinja template *.bu yaml files from basedir and inline all local references
        # merged_dict= base_dict -> security_dict > loaded_dict -> fcos_dict
        merged_dict = pulumi.Output.all(
            base_dict=base_dict,
            security_dict=security_dict,
            fcos_dict=fcos_dict,
            loaded_dict=self.load_butane_files(basedir, this_env),
        ).apply(
            lambda args: merge_dict_struct(
                args["fcos_dict"],
                merge_dict_struct(
                    args["loaded_dict"],
                    merge_dict_struct(args["security_dict"], args["base_dict"]),
                ),
            )
        )

        # 5. apply additional template filters
        self.butane_config = pulumi.Output.all(merged_dict=merged_dict).apply(
            lambda args: yaml.safe_dump(
                self.template_files(args["merged_dict"], this_dir, this_env)
            )
        )

        # 6. translate merged butane yaml to saltstack salt yaml config
        # append this_dir/coreos-update-config.sls and basedir/*.sls to it
        self.saltstack_config = pulumi.Output.concat(
            pulumi.Output.all(butane=self.butane_config).apply(
                lambda args: jinja_run_template(
                    "butane2salt.jinja",
                    [basedir, this_dir],
                    {**this_env, "butane": yaml.safe_load(args["butane"])},
                )
            ),
            open(os.path.join(this_dir, "coreos-update-config.sls"), "r").read(),
            *[open(f, "r").read() for f in glob.glob(os.path.join(basedir, "*.sls"))],
        )

        # self.saltstack_config.apply(log_warn)

        # 7. translate merged butane yaml to ignition json config
        # XXX due to pulumi-command exit 1 on stderr output, we silence stderr,
        #   but output is vital for finding compilation warning and errors, so remove 2>/dev/null on debug
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

        self.result = self.ignition_config.stdout
        self.register_outputs({})

    def load_butane_files(self, basedir, environment, subdir=""):
        "read and jinja template all basedir/*.bu files from basedir recursive, parse as yaml, merge together"

        all_files = sorted(
            [
                fname
                for fname in glob.glob(
                    os.path.join(subdir, "**", "*.bu"), recursive=True, root_dir=basedir
                )
            ]
        )

        merged_yaml = {}
        for fname in all_files:
            yaml_dict = pulumi.Output.all(fname=fname, env=environment).apply(
                lambda args: yaml.safe_load(
                    jinja_run_template(args["fname"], basedir, args["env"])
                )
            )
            merged_yaml = pulumi.Output.all(
                yaml1_dict=merged_yaml, yaml2_dict=yaml_dict
            ).apply(
                lambda args: merge_dict_struct(args["yaml1_dict"], args["yaml2_dict"])
            )

        return merged_yaml

    def template_files(self, yaml_dict, basedir, environment):
        """additional template translation of contents from butane local references where template =! None

        - storage:files[].contents.template
        - systemd:units[].template
        - systemd:units[].dropins[].template

        - template= "jinja"
            - template the source through jinja

        - template= "selinux"
            - compile source selinux text configuration to binary as file:contents.source:data url
            - available for storage.files only

        """

        ydict = copy.deepcopy(yaml_dict)

        if "storage" in ydict and "files" in ydict["storage"]:
            for fnr in range(len(ydict["storage"]["files"])):
                f = ydict["storage"]["files"][fnr]

                if "contents" in f and "template" in f["contents"]:
                    if f["contents"]["template"] not in ["jinja", "selinux"]:
                        raise ValueError(
                            "Invalid option, template must be one of: jinja, selinux"
                        )
                    if "local" in f["contents"]:
                        fname = f["contents"]["local"]
                        del ydict["storage"]["files"][fnr]["contents"]["local"]
                        ydict["storage"]["files"][fnr]["contents"].update(
                            {"inline": open(join_paths(basedir, fname), "r").read()}
                        )
                        f = ydict["storage"]["files"][fnr]
                    if "inline" not in f["contents"]:
                        raise ValueError(
                            "Invalid option, contents must be one of 'local' or 'inline' if template != None"
                        )
                    if f["contents"]["template"] == "jinja":
                        data = jinja_run(f["contents"]["inline"], basedir, environment)
                        ydict["storage"]["files"][fnr]["contents"].update(
                            {"inline": data}
                        )
                    elif f["contents"]["template"] == "selinux":
                        data = "data:;base64," + base64.b64encode(
                            compile_selinux_module(f["contents"]["inline"])
                        ).decode("utf-8")
                        del ydict["storage"]["files"][fnr]["contents"]["inline"]
                        ydict["storage"]["files"][fnr]["contents"].update(
                            {"source": data}
                        )

        if "systemd" in ydict and "units" in ydict["systemd"]:
            for unr in range(len(ydict["systemd"]["units"])):
                u = ydict["systemd"]["units"][unr]
                if "template" in u and u["template"] not in ["jinja"]:
                    raise ValueError("Invalid option, template must be one of: jinja")
                if "contents_local" in u and "template" in u:
                    fname = u["contents_local"]
                    del ydict["systemd"]["units"][unr]["contents_local"]
                    ydict["systemd"]["units"][unr].update(
                        {"contents": open(join_paths(basedir, fname), "r").read()}
                    )
                    u = ydict["systemd"]["units"][unr]
                if "contents" in u and "template" in u:
                    data = jinja_run(u["contents"], basedir, environment)
                    ydict["systemd"]["units"][unr].update({"contents": data})

                if "dropins" in u:
                    for dnr in range(len(u["dropins"])):
                        d = ydict["systemd"]["units"][unr]["dropins"][dnr]
                        if "contents_local" in d and "template" in d:
                            fname = d["contents_local"]
                            del ydict["systemd"]["units"][unr]["dropins"][dnr][
                                "contents_local"
                            ]
                            ydict["systemd"]["units"][unr]["dropins"][dnr].update(
                                {
                                    "contents": open(
                                        join_paths(basedir, fname), "r"
                                    ).read()
                                }
                            )
                            d = ydict["systemd"]["units"][unr]["dropins"][dnr]
                        if "contents" in d and "template" in d:
                            data = jinja_run(d["contents"], basedir, environment)
                            ydict["systemd"]["units"][unr]["dropins"][dnr].update(
                                {"contents": data}
                            )
        return ydict

    def inline_local_files(self, basedir, yaml_dict):
        """inline the contents of butane local references

        - storage:trees:[]:local -> files:[]:contents:inline
        - storage:files:[]:contents:local -> []:contents:inline
        - systemd:units:[]:contents_local -> []:contents
        - systemd:units:[]:dropins:[]:contents_local -> []:contents

        """

        def read_include(basedir, *filepaths):
            return open(join_paths(basedir, *filepaths), "r").read()

        ydict = copy.deepcopy(yaml_dict)

        if "storage" in ydict and "trees" in ydict["storage"]:
            for tnr in range(len(ydict["storage"]["trees"])):
                t = ydict["storage"]["trees"][tnr]
                for lf in glob.glob(
                    join_paths(basedir, t["local"], "**"), recursive=True
                ):
                    if os.path.isfile(lf):
                        rf = join_paths(
                            t["path"] if "path" in t else "/",
                            os.path.relpath(lf, join_paths(basedir, t["local"])),
                        )
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
        if not image_format:
            image_format = defaults["fcos"]["format"]

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
            ca_factory.root_cert_pem.apply(
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

        # download qemu base image
        self.baseimage = FcosImageDownloader(
            platform="qemu", image_format="qcow2.xz", opts=child_opts
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
        root_dir = "/run/user/1000/coreos-update-config"
        update_fname = "coreos-update-config.service"
        update_str = open(os.path.join(this_dir, update_fname), "r").read()

        # transport update service file and main.sls (translated butane) to root_dir and sls_dir
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
                        sudo systemctl restart --wait coreos-update-config""".format(
                source=os.path.join(root_dir, update_fname),
                target=os.path.join("/etc/systemd/system", update_fname),
            ),
            simulate=False,
            triggers=self.config_deployed.triggers,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
        )

        self.result = self.config_updated
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


def compile_selinux_module(content):
    timeout_seconds = 10
    chk_process = subprocess.Popen(
        ["checkmodule", "-M", "-m", "-o", "/dev/stdout", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    chk_output, chk_error = chk_process.communicate(
        input=content, timeout=timeout_seconds
    )
    if chk_process.returncode != 0:
        raise Exception("checkmodule failed:\n{}".format(chk_error))
    pkg_process = subprocess.Popen(
        ["semodule_package", "-o", "/dev/stdout", "-m", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pkg_output, pkg_error = pkg_process.communicate(
        input=chk_output, timeout=timeout_seconds
    )
    if pkg_process.returncode != 0:
        raise Exception("semodule_package failed:\n{}".format(pkg_error))

    return pkg_output
