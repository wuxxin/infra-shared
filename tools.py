#!/usr/bin/env python
"""
## Pulumi - Tools

https:
- f: serve_simple
- c: ServePrepare
- c: ServeOnce
- p: merge_payload_config

ssh:
- f: ssh_put
- f: ssh_deploy
- f: ssh_execute
- f: ssh_get

storage:
- f: write_removable
- f: encrypted_local_export
- f: public_local_export

tool:
- f: log_warn
- c: LocalSaltCall
- c: RemoteSaltCall
- r: TimedResource
- p: get_ip_from_ifname
- p: get_default_host_ip
- p: get_default_gateway_ip
- p: sha256sum_file
- p: yaml_loads

"""

import hashlib
import os
import random
import time
import uuid

from typing import Any, Optional, Type, Dict

import pulumi
import pulumi.dynamic
import pulumi_command as command
import yaml

from pulumi.output import Input, Output
from .template import join_paths

this_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(this_dir, ".."))


def log_warn(x):
    "write str(var) to pulumi.log.warn with line numbering, to be used as var.apply(log_warn)"
    pulumi.log.warn(
        "\n".join(
            ["{}:{}".format(nr + 1, line) for nr, line in enumerate(str(x).splitlines())]
        )
    )


def yaml_loads(s: Input[str], *, Loader: Optional[Type[yaml.Loader]] = None) -> "Output[Any]":
    """
    Uses yaml.safe_load to deserialize the given YAML Input[str] value into a value.

    Args:
        s: The YAML string to deserialize.  This should be an Input[str].
        Loader:  Optional YAML Loader to use. Defaults to yaml.SafeLoader.
    Returns:
        An Output[Any] representing the deserialized YAML value.
    """

    def loads(s: str) -> Any:
        # default to SafeLoader for security
        loader_to_use = Loader or yaml.SafeLoader
        try:
            return yaml.load(s, Loader=loader_to_use)
        except yaml.YAMLError as e:
            raise Exception(f"Failed to parse YAML: {e}") from e

    s_output: Output[str] = Output.from_input(s)
    return s_output.apply(loads)


def sha256sum_file(filename):
    "sha256sum of file, logically backported from python 3.11"

    h = hashlib.sha256()
    buf = bytearray(2**18)
    view = memoryview(buf)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(view):
            h.update(view[:n])
    return h.hexdigest()


def get_ip_from_ifname(name: str) -> str | None:
    """
    Retrieves the first IPv4 address associated with a given network interface name.

    Args:
        name (str): The name of the network interface (e.g., "eth0", "wlan0", "enp7s0")
    Returns:
        str | None: The first IPv4 address found on the interface,
            or None if the interface doesn't exist or has no IPv4 addresses.
    """
    import netifaces

    try:
        # Check if the interface exists
        if name not in netifaces.interfaces():
            return None

        # Get all addresses associated with the interface
        addresses = netifaces.ifaddresses(name)

        # Check if the interface has any IPv4 addresses
        if netifaces.AF_INET not in addresses:
            return None

        # Iterate through IPv4 addresses and return the first one that's not loopback.
        for addr_info in addresses[netifaces.AF_INET]:
            ip_addr = addr_info["addr"]
            if not ip_addr.startswith("127.") and not ip_addr.startswith("::1"):
                return ip_addr
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def get_default_gateway_ip():
    """
    Return the IP address (as a string) of the default gateway, or None if not found
    """
    import netifaces

    try:
        gws = netifaces.gateways()
        default_gateway = gws.get("default", {}).get(netifaces.AF_INET, None)

        if default_gateway:
            # The gateway IP is the first element
            return default_gateway[0]
        else:
            return None
    except (ValueError, KeyError, OSError) as e:
        print(f"Error getting default gateway IP: {e}")
        return None


def get_default_host_ip():
    """
    Return the IP address of the interface that is most likely connected to the outside world.

    This function attempts to find the default gateway and then determine the IP address
    of the interface associated with that gateway.

    Returns:
        str: The IP address of the most likely external interface, or None if not found.
    """
    import netifaces

    try:
        # Get the default gateway
        gws = netifaces.gateways()
        default_gateway = gws.get("default", {}).get(netifaces.AF_INET, None)

        if default_gateway is None:
            # No default gateway found
            return None

        interface = default_gateway[1]
        # Get addresses associated with the interface
        addresses = netifaces.ifaddresses(interface).get(netifaces.AF_INET, [])

        if not addresses:
            return None

        for addr in addresses:
            ip_addr = addr["addr"]
            if not ip_addr.startswith("127.") and not ip_addr.startswith("::1"):
                return ip_addr
        return None

    except (ValueError, KeyError, OSError) as e:
        print(f"Error getting default host IP: {e}")
        return None


class SSHPut(pulumi.ComponentResource):
    """Pulumi Component: use with function ssh_put()"""

    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHPut", name, None, opts)

        self.props = props
        self.triggers = []
        for key, value in self.props["files"].items():
            setattr(self, key, self.__transfer(name, key, value))
        self.register_outputs({})

    def __transfer(self, name, remote_path, local_path):
        resource_name = "{}_put_{}".format(name, remote_path.replace("/", "_"))
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
        full_local_path = join_paths(self.props["local_prefix"], local_path)
        triggers = [
            hashlib.sha256(full_remote_path.encode("utf-8")).hexdigest(),
            pulumi.Output.concat(sha256sum_file(full_local_path)),
        ]
        self.triggers.extend(triggers)

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            copy_cmd = "cp {} {}"
            rm_cmd = "rm {} || true" if self.props["delete"] else ""

            file_transfered = command.local.Command(
                resource_name,
                create=copy_cmd.format(full_local_path, tmpfile),
                delete=rm_cmd.format(tmpfile),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            file_transfered = command.remote.CopyFile(
                resource_name,
                local_path=full_local_path,
                remote_path=full_remote_path,
                connection=command.remote.ConnectionArgs(
                    host=self.props["host"],
                    port=self.props["port"],
                    user=self.props["user"],
                    private_key=self.props["sshkey"].private_key_openssh.apply(lambda x: x),
                ),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        return file_transfered


class SSHSftp(pulumi.CustomResource):
    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHSftp", name, props, opts)
        self.props = props

    def download_file(self, remote_path, local_path):
        import paramiko

        privkey = paramiko.RSAKey(
            data=self.props["sshkey"].private_key_openssh.apply(lambda x: x)
        )
        ssh = paramiko.SSHClient()
        ssh.load_host_keys("")
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            self.props["host"],
            self.props["port"],
            username=self.props["user"],
            pkey=privkey,
        )
        sftp = ssh.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        ssh.close()
        return sha256sum_file(local_path)

    def create(self):
        self.result = self.download_file(self.props["remote_path"], self.props["local_path"])


class SSHGet(pulumi.ComponentResource):
    """Pulumi Component: use with function ssh_get()"""

    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHGet", name, None, opts)
        self.props = props
        self.triggers = []
        for key, value in self.props["files"].items():
            setattr(self, key, self.__transfer(name, key, value))
        self.register_outputs({})

    def __transfer(self, name, remote_path, local_path):
        resource_name = "get_{}".format(remote_path.replace("/", "_"))
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
        full_local_path = join_paths(self.props["local_prefix"], local_path)
        triggers = [
            hashlib.sha256(full_remote_path.encode("utf-8")).hexdigest(),
            pulumi.Output.concat(sha256sum_file(full_local_path)),
        ]
        self.triggers.extend(triggers)

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            copy_cmd = "cp {} {}"
            rm_cmd = "rm {} || true" if self.props["delete"] else ""

            file_transfered = command.local.Command(
                resource_name,
                create=copy_cmd.format(full_local_path, tmpfile),
                delete=rm_cmd.format(tmpfile),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            file_transfered = SSHSftp(
                resource_name,
                props={
                    "host": self.props["host"],
                    "user": self.props["user"],
                    "port": self.props["port"],
                    "sshkey": self.props["sshkey"],
                    "remote_path": remote_path,
                    "local_path": local_path,
                },
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        return file_transfered


class SSHDeployer(pulumi.ComponentResource):
    """Pulumi Component: use with function ssh_deploy()"""

    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHDeployer", name, None, opts)

        self.props = props
        self.triggers = []
        for key, value in self.props["files"].items():
            setattr(self, key, self.__deploy(name, key, value))
        self.register_outputs({})

    def __deploy(self, name, remote_path, data):
        resource_name = "{}_deploy_{}".format(name, remote_path.replace("/", "_"))
        cat_cmd = (
            'x="{}" && mkdir -m 0700 -p $(dirname "$x") && umask 066 && cat - > "$x"'
            if self.props["secret"]
            else 'x="{}" && mkdir -p $(dirname "$x") && cat - > "$x"'
        )
        rm_cmd = "rm {} || true" if self.props["delete"] else ""
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
        triggers = [
            hashlib.sha256(cat_cmd.format(full_remote_path).encode("utf-8")).hexdigest(),
            data.apply(lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()),
        ]
        self.triggers.extend(triggers)

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            value_deployed = command.local.Command(
                resource_name,
                create=cat_cmd.format(tmpfile),
                update=cat_cmd.format(tmpfile),
                delete=rm_cmd.format(tmpfile),
                stdin=data.apply(lambda x: str(x)),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            value_deployed = command.remote.Command(
                resource_name,
                connection=command.remote.ConnectionArgs(
                    host=self.props["host"],
                    port=self.props["port"],
                    user=self.props["user"],
                    private_key=self.props["sshkey"].private_key_openssh.apply(lambda x: x),
                ),
                create=cat_cmd.format(full_remote_path),
                update=cat_cmd.format(full_remote_path),
                delete=rm_cmd.format(full_remote_path),
                stdin=data.apply(lambda x: str(x)),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        return value_deployed


def ssh_put(
    prefix,
    host,
    user,
    files={},
    remote_prefix="",
    local_prefix="",
    port=22,
    delete=False,
    simulate=None,
    opts=None,
):
    """copy/put a set of files from localhost to ssh target using ssh/sftp

    Args:
        files: {remotepath: localpath,}
        remote_prefix: path prefixed to each remotepath
        local_prefix: path prefixed to each locallpath
        if delete==True: files will be deleted from target on deletion of resource
        if simulate==True: files are not transfered but written out to state/tmp/stack_name
        if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    Returns:
        [attr(remotepath, remote.CopyFile|local.Command) for remotepath in files]
        triggers: list of key and data hashes for every file,
            can be used for triggering another function if any file changed

    Example:
    ```python
    config_copied = ssh_put(resource_name, host, user, files=files_dict)
    config_activated = ssh_execute(resource_name, host, user, cmdline=cmdline,
        triggers=config_copied.triggers,
        opts=pulumi.ResourceOptions(depends_on=[config_copied]))
    ```
    """

    from .authority import ssh_factory

    stack_name = pulumi.get_stack()
    props = {
        "host": host,
        "port": port,
        "user": user,
        "files": files,
        "sshkey": ssh_factory.provision_key,
        "delete": delete,
        "remote_prefix": remote_prefix,
        "local_prefix": local_prefix,
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    transfered = SSHPut(prefix, props, opts=opts)
    # pulumi.export("{}_put".format(prefix), transfered)
    return transfered


def ssh_get(
    prefix,
    host,
    user,
    files={},
    remote_prefix="",
    local_prefix="",
    port=22,
    simulate=None,
    triggers=None,
    opts=None,
):
    """get/copy a set of files from the target system to the local filesystem using ssh/sftp

    Args:
        files: {remotepath: localpath,}
        remote_prefix: path prefixed to each remotepath
        local_prefix: path prefixed to each locallpath
        if simulate==True: files are not transfered but written out to state/tmp/stack_name
        if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    Returns:
        [attr(remotepath, paramiko.sendfile) for remotepath in files]
        triggers: list of key and data hashes for every file,
            can be used for triggering another function if any file changed
    """

    from .authority import ssh_factory

    stack_name = pulumi.get_stack()
    props = {
        "host": host,
        "port": port,
        "user": user,
        "files": files,
        "sshkey": ssh_factory.provision_key,
        "remote_prefix": remote_prefix,
        "local_prefix": local_prefix,
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    transfered = SSHGet(prefix, props, opts=opts)
    # pulumi.export("{}_get".format(prefix), transfered)
    return transfered


def ssh_deploy(
    prefix,
    host,
    user,
    files={},
    remote_prefix="",
    port=22,
    secret=False,
    delete=False,
    simulate=None,
    opts=None,
):
    """deploy a set of strings as small files to a ssh target

    Args:
        files: {remotepath: data,}
        remote_prefix= path prefixed to each remotepath
        if secret==True: data is considered a secret, file mode will be 0600, dir mode will be 0700
        if delete==True: files will be deleted from target on deletion of resource
        if simulate==True: data is not transfered but written out to state/tmp/stack_name
        if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    Returns:
        [attr(remotepath, remote.Command|local.Command) for remotepath in files]
        triggers: list of key and data hashes for every file,
            can be used for triggering another function if any file changed

    Example:
    ```python
    config_deployed = ssh_deploy(resource_name, host, user, files=config_dict)
    config_activated = ssh_execute(resource_name, host, user, cmdline=cmdline,
        triggers=config_deployed.triggers,
        opts=pulumi.ResourceOptions(depends_on=[config_deployed]))
    ```
    """
    from .authority import ssh_factory

    stack_name = pulumi.get_stack()
    props = {
        "host": host,
        "port": port,
        "user": user,
        "files": files,
        "remote_prefix": remote_prefix,
        "sshkey": ssh_factory.provision_key,
        "secret": secret,
        "delete": delete,
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    deployed = SSHDeployer(prefix, props, opts=opts)
    # pulumi.export("{}_deploy".format(prefix), deployed)
    return deployed


def ssh_execute(
    prefix,
    host,
    user,
    cmdline,
    environment={},
    port=22,
    simulate=None,
    triggers=None,
    opts=None,
):
    """execute cmdline with environment as user on a ssh target host

    Args:
        cmdline: String to be executed on target host
        environment: Dict of environment entries to be available in cmdline
        if simulate==True: command is not executed but written out to state/tmp/stack_name
        if simulate==None: simulate = pulumi.get_stack().endswith("sim")

    """

    from .authority import ssh_factory

    resource_name = "{}_ssh_execute".format(prefix)
    stack_name = pulumi.get_stack()
    simulate = stack_name.endswith("sim") if simulate is None else simulate

    if simulate:
        tmpdir = os.path.join(project_dir, "state", "tmp", stack_name)
        os.makedirs(tmpdir, exist_ok=True)
        # XXX write out environment if not empty on simulate, so we can look what env was set
        if environment != {}:
            cmdline = (
                "\n".join(["{k}={v}".format(k=k, v=v) for k, v in environment.items()])
                + "\n"
                + cmdline
            )
        ssh_executed = command.local.Command(
            resource_name,
            create="cat - > {}".format(os.path.join(tmpdir, resource_name)),
            delete="rm {} || true".format(os.path.join(tmpdir, resource_name)),
            stdin=cmdline,
            triggers=triggers,
            opts=opts,
        )
    else:
        ssh_executed = command.remote.Command(
            resource_name,
            connection=command.remote.ConnectionArgs(
                host=host,
                port=port,
                user=user,
                private_key=ssh_factory.provision_key.private_key_openssh.apply(lambda x: x),
            ),
            create=cmdline,
            triggers=triggers,
            environment=environment,
            opts=opts,
        )
    return ssh_executed


class DataExport(pulumi.ComponentResource):
    """store state data (with optional encryption) as local files under state/files/

    use with
        - public_local_export()
        - encrypted_local_export()
    """

    def __init__(self, prefix, filename, data, key=None, filter="", delete=False, opts=None):
        super().__init__("pkg:index:DataExport", "_".join([prefix, filename]), None, opts)

        stack_name = pulumi.get_stack()
        filter += " | " if filter else ""

        if key:
            self.filename = os.path.join(
                project_dir,
                "state",
                "files",
                stack_name,
                prefix,
                "{}.age".format(filename),
            )
            create_cmd = pulumi.Output.concat(
                filter,
                "age -R ",
                os.path.join(project_dir, "authorized_keys"),
                " -r '",
                key,
                "' -o ",
                self.filename,
            )

        else:
            self.filename = os.path.join(
                project_dir, "state", "files", stack_name, "public", prefix, filename
            )
            create_cmd = pulumi.Output.concat(filter, "cat - > ", self.filename)

        resource_name = "{}_{}local_storage_{}".format(
            prefix,
            "public_" if not key else "",
            os.path.basename(self.filename).replace("/", "_"),
        )
        delete_cmd = "rm {} | true".format(self.filename) if delete else ""

        os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        self.saved = command.local.Command(
            resource_name,
            create=create_cmd,
            update=create_cmd,
            delete=delete_cmd,
            stdin=data,
            opts=opts,
            dir=project_dir,
            triggers=[
                data.apply(lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()),
            ],
        )
        self.register_outputs({})


def encrypted_local_export(prefix, filename, data, filter="", delete=False, opts=None):
    "store sensitive state data age encrypted in state/files/"

    from .authority import ssh_factory

    return DataExport(
        prefix,
        filename,
        data,
        ssh_factory.authorized_keys,
        filter=filter,
        delete=delete,
        opts=opts,
    )


def public_local_export(prefix, filename, data, filter="", delete=False, opts=None):
    "store public state data unencrypted in state/files/"

    return DataExport(prefix, filename, data, filter=filter, delete=delete, opts=opts)


def salt_config(resource_name, stack_name, base_dir):
    """generate a saltstack salt config

    grains available:
      - resource_name, base_dir, root_dir, tmp_dir, sls_dir, pillar_dir

    """

    root_dir = os.path.join(base_dir, "state", "salt", stack_name, resource_name)
    tmp_dir = os.path.join(base_dir, "state", "tmp", stack_name, resource_name)
    sls_dir = os.path.join(root_dir, "sls")
    pillar_dir = os.path.join(root_dir, "pillar")

    config = yaml.safe_load(
        """
id: {resource_name}
local: true
file_client: local
default_top: base
state_top: top.sls
fileserver_followsymlinks: true
fileserver_ignoresymlinks: false
fileserver_backend:
  - roots
file_roots:
  base:
    - {sls_dir}
pillar_roots:
  base:
    - {pillar_dir}
grains:
  resource_name: {resource_name}
  base_dir: {base_dir}
  root_dir: {root_dir}
  tmp_dir: {tmp_dir}
  sls_dir: {sls_dir}
  pillar_dir: {pillar_dir}
root_dir: {root_dir}
conf_file: {root_dir}/minion
pki_dir: {root_dir}/etc/salt/pki/minion
pidfile: {root_dir}/var/run/salt-minion.pid
sock_dir: {root_dir}/var/run/salt/minion
cachedir: {root_dir}/var/cache/salt/minion
extension_modules: {root_dir}/var/cache/salt/minion/extmods
log_level_logfile: quiet
log_file: /dev/null

""".format(
            resource_name=resource_name,
            base_dir=base_dir,
            root_dir=root_dir,
            tmp_dir=tmp_dir,
            sls_dir=sls_dir,
            pillar_dir=pillar_dir,
        )
    )
    return config


class LocalSaltCall(pulumi.ComponentResource):
    """configure and execute a saltstack salt-call on a local provision machine

    - sls_dir defaults to project_dir
    - config/run/tmp/cache and other files default to state/salt/stackname/resource_name
    - grains from salt_config available

    Args:
        *args: salt command to execute
        pillar: dict to use as pillar
        environment: dict to use as process environment

    Example:
    ```python
    # build openwrt image
    LocalSaltCall("build_openwrt", "state.sls", "build_openwrt",
        pillar={}, environment={}, sls_dir=this_dir)
    ```
    """

    def __init__(
        self,
        resource_name,
        *args,
        pillar={},
        environment={},
        sls_dir=None,
        opts=None,
        **kwargs,
    ):
        super().__init__("pkg:index:LocalSaltCall", resource_name, None, opts)
        stack = pulumi.get_stack()
        self.config = salt_config(resource_name, stack, project_dir)
        pillar_dir = self.config["grains"]["pillar_dir"]
        dest_sls_dir = self.config["grains"]["sls_dir"]

        os.makedirs(self.config["root_dir"], exist_ok=True)
        os.makedirs(pillar_dir, exist_ok=True)
        if not sls_dir:
            sls_dir = project_dir
        if os.path.islink(dest_sls_dir) and os.readlink(dest_sls_dir) != sls_dir:
            os.remove(dest_sls_dir)
        if not os.path.exists(dest_sls_dir):
            os.symlink(sls_dir, dest_sls_dir, target_is_directory=True)

        with open(self.config["conf_file"], "w") as m:
            m.write(yaml.safe_dump(self.config))
        with open(os.path.join(pillar_dir, "top.sls"), "w") as m:
            m.write("base:\n  '*':\n    - main\n")
        with open(os.path.join(pillar_dir, "main.sls"), "w") as m:
            m.write(yaml.safe_dump(pillar))

        self.executed = command.local.Command(
            resource_name,
            create="uv run {scripts_dir}/salt-call.py -c {conf_dir} {args}".format(
                scripts_dir=os.path.join(this_dir, "scripts"),
                conf_dir=self.config["root_dir"],
                args=" ".join(args),
            ),
            environment=environment,
            opts=pulumi.ResourceOptions(parent=self),
            **kwargs,
        )
        self.result = self.executed
        self.register_outputs({})


class RemoteSaltCall(pulumi.ComponentResource):
    """configure and execute a saltstack salt-call on a remote target machine

    - grains from salt_config available
    - NOTE: function replaces parameters "{base_dir}" and "{args}" in the "exec" string
        - therefore avoid (rename) shell vars named "${base_dir}" or "${args}"

    """

    def __init__(
        self,
        resource_name,
        host,
        user,
        base_dir,
        *args,
        pillar={},
        salt="",
        environment={},
        root_dir=None,
        tmp_dir=None,
        sls_dir=None,
        exec="/usr/bin/salt-call -c {base_dir} {args}",
        opts=None,
        **kwargs,
    ):
        super().__init__(
            "pkg:index:RemoteSaltCall",
            "{}_{}".format(resource_name, user),
            None,
            opts,
        )

        stack = pulumi.get_stack()
        self.config = salt_config(
            resource_name,
            stack,
            base_dir,
            root_dir=root_dir,
            tmp_dir=tmp_dir,
            sls_dir=sls_dir,
        )
        pillar_dir = self.config["grains"]["pillar_dir"]
        sls_dir = self.config["grains"]["sls_dir"]
        rel_pillar_dir = os.path.relpath(pillar_dir, base_dir)
        rel_sls_dir = os.path.relpath(sls_dir, base_dir)

        self.config_dict = {
            os.path.relpath(self.config["conf_file"], base_dir): pulumi.Output.from_input(
                yaml.safe_dump(self.config)
            ),
            os.path.join(rel_sls_dir, "top.sls"): pulumi.Output.from_input(
                "base:\n  '*':\n    - main\n"
            ),
            os.path.join(rel_sls_dir, "main.sls"): pulumi.Output.from_input(salt),
            os.path.join(rel_pillar_dir, "top.sls"): pulumi.Output.from_input(
                "base:\n  '*':\n    - main\n"
            ),
            os.path.join(rel_pillar_dir, "main.sls"): pulumi.Output.from_input(
                yaml.safe_dump(pillar)
            ),
        }

        self.config_deployed = ssh_deploy(
            resource_name,
            host,
            user,
            self.config_dict,
            remote_prefix=base_dir,
            simulate=False,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.salt_executed = ssh_execute(
            resource_name,
            host,
            user,
            cmdline=exec.format(
                base_dir=self.config["root_dir"],
                args=" ".join(args),
            ),
            simulate=False,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
            **kwargs,
        )

        self.register_outputs({})


class _TimedResourceProviderInputs:
    """
    Helper class to represent the unwrapped inputs to the provider.
    """

    def __init__(
        self,
        timeout_sec: str,
        creation_type: str,
        base: Optional[str],
        range: Optional[str],
    ):
        self.timeout_sec = timeout_sec
        self.creation_type = creation_type
        self.base = base
        self.range = range


class TimedResourceProvider(pulumi.dynamic.ResourceProvider):
    """
    Dynamic resource provider for TimedResource
    """

    def _now(self) -> int:
        """Returns the current time as a Unix timestamp (seconds)."""
        return int(time.time())

    def _generate_value(
        self, creation_type: str, base: Optional[str], range: Optional[str]
    ) -> str:
        """
        Generates a value based on the creation type
        """
        if creation_type == "random_int":
            if base is None or range is None:
                raise ValueError("For 'random_int', 'base' and 'range' must be provided.")
            return str(random.randint(int(base), int(base) + int(range) - 1))
        elif creation_type == "unixtime":
            return str(self._now())
        elif creation_type == "uuid":
            return str(uuid.uuid4())
        else:
            raise ValueError(f"Invalid creation_type: {creation_type}")

    def create(self, props: _TimedResourceProviderInputs) -> pulumi.dynamic.CreateResult:
        """
        Creates a new TimedResource
        """
        value = self._generate_value(
            props["creation_type"], props.get("base"), props.get("range")
        )
        last_updated = self._now()
        return pulumi.dynamic.CreateResult(
            id_=str(uuid.uuid4()),
            outs={"value": str(value), "last_updated": str(last_updated)},
        )

    def read(self, id_: str, props: _TimedResourceProviderInputs) -> pulumi.dynamic.ReadResult:
        """
        Reads the state of an existing TimedResource
        """
        return pulumi.dynamic.ReadResult(id_=id_, outs=props)

    def diff(
        self,
        id_: str,
        old_inputs: Dict[str, Any],
        new_inputs: _TimedResourceProviderInputs,
    ) -> pulumi.dynamic.DiffResult:
        """Checks if the resource needs to be updated

        Args:
            id_: The resource ID.
            old_inputs: The previous input properties.
            new_inputs: The new input properties.
        Returns:
           A DiffResult indicating if changes are needed and which inputs changed
        """
        timeout_sec = int(new_inputs["timeout_sec"])
        last_updated = int(old_inputs["last_updated"])
        now = self._now()

        changes = (now - last_updated) > timeout_sec
        return pulumi.dynamic.DiffResult(changes=changes)

    def update(
        self, id_: str, _olds: Dict[str, Any], new_inputs: _TimedResourceProviderInputs
    ) -> pulumi.dynamic.UpdateResult:
        """Updates an existing TimedResource

        Args:
            id_: The resource ID
            _olds: The previous output properties
            new_inputs: The new input properties
        Returns:
            The UpdateResult containing the updated output properties
        """
        value = self._generate_value(
            new_inputs["creation_type"], new_inputs.get("base"), new_inputs.get("range")
        )
        last_updated = self._now()
        return pulumi.dynamic.UpdateResult(
            outs={"value": str(value), "last_updated": str(last_updated)}
        )

    def delete(self, id: str, props: Dict[str, Any]) -> None:
        """
        Deletes a TimedResource.
        """
        # pulumi will do the deletion
        pass


class TimedResourceInputs:
    """
    Input properties for TimedResource.

    :param int timeout_sec: timeout in seconds the service will be available
    :param str creation_type: one of "random_int", "unixtime", "uuid"
    :param int base: base number for random_int
    :param int range: range for random_int
    """

    def __init__(
        self,
        timeout_sec: pulumi.Input[int],
        creation_type: pulumi.Input[str],
        base: Optional[pulumi.Input[int]] = None,
        range: Optional[pulumi.Input[int]] = None,
    ):
        self.timeout_sec = timeout_sec
        self.creation_type = creation_type
        self.base = base
        self.range = range


class TimedResource(pulumi.dynamic.Resource):
    """
    Custom resource that regenerates a value based on a specified type of logic if a timeout has passed.
    """

    value: pulumi.Output[str]
    last_updated: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        args: TimedResourceInputs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            TimedResourceProvider(),
            name,
            {"value": None, "last_updated": None, **vars(args)},
            opts,
        )


class ServePrepare(pulumi.ComponentResource):
    """a serve-prepare component to configure a future available web resource

    It creates a `TimedResource` object to manage the local port configuration
    and another `TimedResource` object to create a request_path uuid
    and initializes port forwarding to the local port if requested.

    Args:
    :param str config_str: yaml str input added on top of the default resource config
    :param int timeout_sec: timeout in seconds the service will be available
    :param int tokenlifetime_sec: lifetime in seconds for the randomized
        port number and path assignments, before it will be recreated on demand
    :param str serve_ip: defaults "": if set, the ip address specified is used for serving
    :param str serve_interface: defaults "": if set, the ip address of the specified interface is used for serving
        else it uses get_default_host_ip(), serve_ip takes precedence over serve_interface
    :param str mtls_clientid: if set, client must present a matching client certificate with cn=mtls_clientid
    :param int port_base: base port number of the web resource
    :param int port_range: range of ports for the web resource

    Attributes:
    :attribute pulumi.Output[dict] config: Final serve config as dict
    :attribute pulumi.Output[str] result: Final serve config as yaml string

    """

    def __init__(
        self,
        resource_name: str,
        config_str: str = "",
        timeout_sec: int = 45,
        tokenlifetime_sec: int = 10 * 60,
        port_base: int = 47000,
        port_range: int = 3000,
        serve_interface: str = "",
        serve_ip: str = "",
        mtls_clientid: str = "",
        opts: pulumi.Input[object] = None,
    ) -> None:
        from .authority import config, ca_factory, provision_host_tls

        super().__init__("pkg:index:ServeConfigure", resource_name, None, opts)

        # Build the initial static config (*without* Output values)
        self.static_config = {
            "timeout": timeout_sec,
            "mtls": False,
            "mtls_clientid": mtls_clientid if mtls_clientid else "",
            "payload": None,
            "port_forward": config.get_object(
                "port_forward", {"enabled": False, "lifetime_sec": tokenlifetime_sec}
            ),
        }
        # Merge in the user-provided config before adding Output-dependent values
        if config_str:
            self.static_config.update(yaml.safe_load(config_str))

        # use the default hostip, or the named interface ip or the specified ip for accessing the url
        self.serve_ip = (
            serve_ip
            if serve_ip
            else (
                get_ip_from_ifname(serve_interface)
                if serve_interface
                else get_default_host_ip()
            )
        )

        # create a network port number, used for https serving the data
        self.local_port_config = TimedResource(
            "local-port-config",
            TimedResourceInputs(
                timeout_sec=tokenlifetime_sec,
                creation_type="random_int",
                base=port_base,
                range=port_range,
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.serve_port = self.local_port_config.value.apply(lambda x: int(x))

        # create a request_path from uuid
        self.request_uuid = TimedResource(
            "request-uuid",
            TimedResourceInputs(timeout_sec=tokenlifetime_sec, creation_type="uuid"),
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.request_path = self.request_uuid.value.apply(lambda x: "/" + x)

        def build_merged_config(args):
            # merge pulumi outputs with static_config
            serve_ip, serve_port, request_path, cert, key, ca_cert = args
            merged_config = self.static_config.copy()
            merged_config.update(
                {
                    "serve_port": serve_port,
                    "request_path": request_path,
                    "cert": cert,
                    "key": key,
                    "ca_cert": ca_cert,
                    "remote_url": f"https://{serve_ip}:{serve_port}{request_path}",
                }
            )
            return merged_config

        # Use .apply() to create a new Output that contains the fully resolved config
        self.merged_config = Output.all(
            self.serve_ip,
            self.serve_port,
            self.request_path,
            provision_host_tls.chain,
            provision_host_tls.key.private_key_pem,
            ca_factory.root_cert_pem,
        ).apply(build_merged_config)

        if self.merged_config["port_forward"]["enabled"] and False:
            # if enabled, run port_forward and update config with returned port_forward values
            self.forward = command.local.Command(
                resource_name + "_forward",
                create=f"uv run {os.path.join(this_dir, 'scripts/port_forward.py')} --yaml-from-stdin --yaml-to-stdout",
                stdin=self.merged_config.apply(yaml.safe_dump),
                opts=pulumi.ResourceOptions(parent=self),
            )

            def update_with_forward(forwarded_config_str):
                forwarded_config = yaml.safe_load(forwarded_config_str)
                updated_config = self.merged_config.apply(lambda x: x.copy())
                return updated_config.apply(
                    lambda conf: {
                        **conf,
                        "remote_url": f"https://{forwarded_config['port_forward']['public_ip']}:{forwarded_config['port_forward']['public_port']}{self.request_path}",
                        "port_forward": forwarded_config["port_forward"],
                    }
                )

            self.config = self.forward.stdout.apply(update_with_forward)
        else:
            self.config = self.merged_config

        # create yaml string of config object as .result
        self.result = self.config.apply(yaml.safe_dump)
        self.register_outputs({})


class ServeOnce(pulumi.ComponentResource):
    """one time secure web data server for single request data, eg. ignition data or one time webhook

    It uses a temporary server that shuts down after the data has been retrieved once.
    The server is configured via YAML passed as `stdin`.

    Args:
        resource_name (str): The name of the resource
        config (pulumi.Input[Dict]): The configuration for the server, provided as a YAML-serializable dict.

    Attributes:
        result (pulumi.Output[str]): The standard output of the `serve_once.py` script.
            This contains any POST information, if provided.

    Example:
    ```python
        ServeOnce("testing", config=merge_payload_config(payload, config))
    ```
    """

    def __init__(self, resource_name, config, opts=None):
        super().__init__("pkg:index:ServeOnce", resource_name, None, opts)
        self.executed = command.local.Command(
            resource_name,
            create=f"uv run {os.path.join(this_dir, 'scripts/serve_once.py')} --verbose --yes",
            stdin=config.apply(yaml.safe_dump),
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.result = self.executed.stdout
        self.register_outputs({})


def merge_payload_config(payload, config):
    """Merges payload (str) into config dictionary"""

    def merge_func(args):
        payload_value = args[0]
        config_value = args[1]
        return {**config_value, "payload": payload_value}

    # Ensure both inputs are resolved before merging
    merged_config = pulumi.Output.all(payload, config).apply(merge_func)
    return merged_config


def serve_simple(resource_name, yaml_str, opts=None):
    config_dict = {"payload": yaml.safe_load(yaml_str)}
    this_config = ServePrepare(
        "serve_prepare_{}".format(resource_name),
        config_str=yaml.safe_dump(config_dict),
        opts=opts,
    )
    return ServeOnce("serve_once_{}".format(resource_name), this_config.config, opts=opts)


class WriteRemovable(pulumi.ComponentResource):
    """Writes image from given image_path to specified serial_numbered removable storage device"""

    def __init__(self, resource_name, image, serial, size=0, patches=None, opts=None):
        super().__init__("pkg:index:WriteRemovable", resource_name, None, opts)

        create_str = (
            "uv run "
            + os.path.join(this_dir, "scripts/write_removable.py")
            + " --silent"
            + " --source-image {}".format(image)
            + " --dest-serial {} --dest-size {}".format(serial, size)
            + "".join([" --patch {} {}".format(source, dest) for source, dest in patches])
        )

        self.executed = command.local.Command(
            resource_name,
            create=create_str,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.result = self.executed.returncode
        self.register_outputs({})


def write_removable(resource_name, image, serial, size=0, patches=None, opts=None):
    return WriteRemovable(
        "write_removable_{}".format(resource_name),
        image=image,
        serial=serial,
        size=size,
        patches=patches,
        opts=opts,
    )
