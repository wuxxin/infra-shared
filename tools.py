#!/usr/bin/env python
"""
## Pulumi - Tools - Serve HTTPS, SSH-put/get/execute, local and Remote Salt-Call, write Removable-Media, State Data Export, Tools

https:
- f: serve_simple
- c: ServePrepare
- c: ServeOnce

ssh:
- f: ssh_put
- f: ssh_deploy
- f: ssh_get
- f: ssh_execute
- c: SSHPut
- c: SSHDeploy
- c: SSHGet
- c: SSHExecute
- d: WaitForHostReady

storage:
- f: write_removable
- f: encrypted_local_export
- f: public_local_export

tool:
- c: LocalSaltCall
- c: RemoteSaltCall
- c: BuildFromSalt

- d: TimedResource
- f: log_warn

- p: salt_config
- p: get_ip_from_ifname
- p: get_default_host_ip
- p: get_default_gateway_ip
- p: sha256sum_file
- p: yaml_loads

"""

import hashlib
import os
import random
import sys
import time
import uuid
import io
import json

from typing import Any, Optional, Type, Dict

import netifaces
import yaml

import pulumi
import pulumi.dynamic
import pulumi_command as command
from pulumi_command.local import Logging as LocalLogging
from pulumi_command.remote import Logging as RemoteLogging
from pulumi.output import Input, Output
from pulumi import ResourceOptions

from .template import join_paths, merge_dict_struct, dict_get_bool

this_dir = os.path.dirname(os.path.normpath(__file__))
project_dir = os.getcwd()


def log_warn(x):
    """Logs a multi-line string to the Pulumi console with line numbers.

    This function is intended to be used with `pulumi.Output.apply` to inspect
    the resolved value of an output.

    Args:
        x (any):
            The value to log. It will be converted to a string.
    """
    pulumi.log.warn(
        "\n".join(
            ["{}:{}".format(nr + 1, line) for nr, line in enumerate(str(x).splitlines())]
        )
    )


def yaml_loads(s: Input[str], *, Loader: Optional[Type[yaml.Loader]] = None) -> "Output[Any]":
    """Deserializes a YAML string into a Pulumi output.

    This function takes a Pulumi input string containing YAML and deserializes
    it into a Pulumi output of the corresponding Python object.

    Args:
        s (Input[str]):
            The YAML string to deserialize.
        Loader (Optional[Type[yaml.Loader]], optional):
            The YAML loader to use. Defaults to `yaml.SafeLoader`.

    Returns:
        Output[Any]:
            A Pulumi output representing the deserialized YAML.

    Raises:
        Exception:
            If the YAML parsing fails.
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
    """Calculates the SHA256 checksum of a file.

    Args:
        filename (str):
            The path to the file.

    Returns:
        str:
            The hexadecimal SHA256 checksum of the file.
    """
    h = hashlib.sha256()
    buf = bytearray(2**18)
    view = memoryview(buf)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(view):
            h.update(view[:n])
    return h.hexdigest()


def get_ip_from_ifname(name: str) -> str | None:
    """Retrieves the first IPv4 address from a network interface.

    Args:
        name (str):
            The name of the network interface (e.g., "eth0").

    Returns:
        str | None:
            The first IPv4 address of the interface, or None if not found.
    """
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
    """Retrieves the IP address of the default gateway.

    Returns:
        str | None:
            The IP address of the default gateway, or None if not found.
    """
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
    """Retrieves the IP address of the default network interface.

    This function determines the default gateway and returns the IP address of
    the associated network interface.

    Returns:
        str | None:
            The IP address of the default interface, or None if not found.
    """
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
    """A Pulumi component for securely copying files to a remote host over SSH."""

    def __init__(self, resource_name, props, opts=None):
        """Initializes an SSHPut component.

        Args:
            resource_name (str):
                The name of the resource.
            props (dict):
                A dictionary of properties for the component.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:SSHPut", resource_name, None, opts)

        def create_resources_and_get_triggers(files_dict, props=props):
            all_triggers = []
            for remote_path, local_path in files_dict.items():
                remote_path_output = pulumi.Output.from_input(remote_path)
                sub_resource_name = remote_path_output.apply(
                    lambda p: "{}_put_{}".format(
                        resource_name.split("-")[0], p.replace("/", "_")
                    )
                )
                full_remote_path = pulumi.Output.all(
                    props["remote_prefix"], remote_path_output
                ).apply(lambda args: join_paths(args[0], args[1]))

                local_path_output = pulumi.Output.from_input(local_path)
                if props["local_prefix"]:
                    full_local_path_output = pulumi.Output.all(
                        props["local_prefix"], local_path_output
                    ).apply(lambda args: join_paths(args[0], args[1]))
                else:
                    full_local_path_output = local_path_output

                file_triggers = [
                    full_remote_path.apply(
                        lambda p: hashlib.sha256(p.encode("utf-8")).hexdigest()
                    ),
                    full_local_path_output.apply(sha256sum_file),
                ]
                all_triggers.extend(file_triggers)

                if props["simulate"]:
                    os.makedirs(props["tmpdir"], exist_ok=True)
                    tmpfile = sub_resource_name.apply(
                        lambda r: os.path.normpath(os.path.join(props["tmpdir"], r))
                    )
                    copy_cmd = pulumi.Output.all(full_local_path_output, tmpfile).apply(
                        lambda args: "cp {} {}".format(args[0], args[1])
                    )
                    rm_cmd = tmpfile.apply(
                        lambda t: "rm {} || true".format(t) if props["delete"] else ""
                    )
                    _ = pulumi.Output.all(sub_resource_name, copy_cmd, rm_cmd).apply(
                        lambda args: command.local.Command(
                            args[0],
                            create=args[1],
                            delete=args[2],
                            triggers=file_triggers,
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
                else:
                    _ = pulumi.Output.all(
                        sub_resource_name, full_remote_path, full_local_path_output
                    ).apply(
                        lambda args: command.remote.CopyFile(
                            args[0],
                            local_path=args[2],
                            remote_path=args[1],
                            connection=command.remote.ConnectionArgs(
                                host=props["host"],
                                port=props["port"],
                                user=props["user"],
                                private_key=props["sshkey"].private_key_openssh,
                            ),
                            triggers=file_triggers,
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
            return all_triggers

        files_output = pulumi.Output.from_input(props["files"])
        all_triggers_output = files_output.apply(create_resources_and_get_triggers)
        self.deployment_hash = all_triggers_output.apply(
            lambda list_of_outputs: pulumi.Output.all(*list_of_outputs).apply(
                lambda resolved_triggers: hashlib.sha256(
                    ",".join(sorted(resolved_triggers)).encode("utf-8")
                ).hexdigest()
            )
        )
        self.register_outputs({})


class SSHSftp(pulumi.CustomResource):
    """A Pulumi custom resource for downloading a file over SFTP."""

    def __init__(self, resource_name, props, opts=None):
        """Initializes an SSHSftp custom resource.

        Args:
            resource_name (str):
                The name of the resource.
            props (dict):
                A dictionary of properties for the resource.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:SSHSftp", resource_name, props, opts)
        self.props = props

    def download_file(self, remote_path, local_path):
        """Downloads a file from a remote host.

        Args:
            remote_path (str):
                The path to the file on the remote host.
            local_path (str):
                The path to save the file to on the local machine.

        It will create the directory path leading to local_path if it does not exist.

        Returns:
            str:
                The SHA256 checksum of the downloaded file.
        """
        import paramiko

        privkey = paramiko.RSAKey(data=self.props["sshkey"].private_key_openssh)
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
        local_dir = os.path.dirname(local_path)
        if not os.path.isdir(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        sftp.get(remote_path, local_path)
        sftp.close()
        ssh.close()
        return sha256sum_file(local_path)

    def create(self, props):
        """Creates the SSHSftp resource.

        Args:
            props (dict):
                The properties for the resource.

        Returns:
            pulumi.dynamic.CreateResult:
                The result of the create operation.
        """
        self.result = self.download_file(props["remote_path"], props["local_path"])
        return pulumi.dynamic.CreateResult(id_=str(uuid.uuid4()), outs={"result": self.result})


class SSHGet(pulumi.ComponentResource):
    """A Pulumi component for securely copying files from a remote host over SSH."""

    def __init__(self, resource_name, props, opts=None):
        """Initializes an SSHGet component.

        Args:
            resource_name (str):
                The name of the resource.
            props (dict):
                A dictionary of properties for the component.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:SSHGet", resource_name, None, opts)

        def create_resources_and_get_triggers(files_dict, props=props):
            all_triggers = []
            for remote_path, local_path in files_dict.items():
                remote_path_output = pulumi.Output.from_input(remote_path)
                sub_resource_name_output = remote_path_output.apply(
                    lambda p: "{}_get_{}".format(
                        resource_name.split("-")[0], p.replace("/", "_")
                    )
                )
                full_remote_path_output = pulumi.Output.all(
                    props["remote_prefix"], remote_path_output
                ).apply(lambda args: join_paths(args[0], args[1]))

                local_path_output = pulumi.Output.from_input(local_path)
                full_local_path_output = pulumi.Output.all(
                    props["local_dir"], props["local_prefix"], local_path_output
                ).apply(lambda args: join_paths(args[0], args[1], args[2]))

                file_triggers = [
                    full_remote_path_output.apply(
                        lambda p: hashlib.sha256(p.encode("utf-8")).hexdigest()
                    ),
                ]
                all_triggers.extend(file_triggers)

                if props["simulate"]:
                    tmpfile = full_local_path_output
                    create_cmd = tmpfile.apply(
                        lambda p: f"mkdir -p $(dirname {p}) && touch {p}"
                    )
                    delete_cmd = (
                        tmpfile.apply(lambda p: f"rm {p} || true") if props["delete"] else ""
                    )
                    _ = pulumi.Output.all(
                        sub_resource_name_output, create_cmd, delete_cmd
                    ).apply(
                        lambda args: command.local.Command(
                            args[0],
                            create=args[1],
                            delete=args[2],
                            triggers=file_triggers,
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
                else:
                    _ = pulumi.Output.all(
                        sub_resource_name_output,
                        full_remote_path_output,
                        full_local_path_output,
                    ).apply(
                        lambda args: SSHSftp(
                            args[0],
                            props={
                                "host": props["host"],
                                "user": props["user"],
                                "port": props["port"],
                                "sshkey": props["sshkey"],
                                "remote_path": args[1],
                                "local_path": args[2],
                            },
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
            return all_triggers

        files_output = pulumi.Output.from_input(props["files"])
        all_triggers_output = files_output.apply(create_resources_and_get_triggers)
        self.deployment_hash = all_triggers_output.apply(
            lambda list_of_outputs: pulumi.Output.all(*list_of_outputs).apply(
                lambda resolved_triggers: hashlib.sha256(
                    ",".join(sorted(resolved_triggers)).encode("utf-8")
                ).hexdigest()
            )
        )
        self.register_outputs({})


class SSHDeploy(pulumi.ComponentResource):
    """A Pulumi component for deploying string data as files to a remote host."""

    def __init__(self, resource_name, props, opts=None):
        """Initializes an SSHDeploy component.

        Args:
            resource_name (str):
                The name of the resource.
            props (dict):
                A dictionary of properties for the component.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:SSHDeploy", resource_name, None, opts)

        def create_resources_and_get_triggers(files_dict, props=props):
            all_triggers = []
            for remote_path, data in files_dict.items():
                remote_path_output = pulumi.Output.from_input(remote_path)
                sub_resource_name = remote_path_output.apply(
                    lambda p: "{}_deploy_{}".format(
                        resource_name.split("-")[0], p.replace("/", "_")
                    )
                )
                data_output = pulumi.Output.from_input(data)
                full_remote_path = pulumi.Output.all(
                    props["remote_prefix"], remote_path_output
                ).apply(lambda args: join_paths(args[0], args[1]))

                cat_cmd_template = (
                    'x="{}" && mkdir -m 0700 -p $(dirname "$x") && umask 066 && cat - > "$x"'
                    if props["secret"]
                    else 'x="{}" && mkdir -p $(dirname "$x") && cat - > "$x"'
                )
                rm_cmd_template = "rm {} || true" if props["delete"] else ""

                cat_cmd = full_remote_path.apply(lambda p: cat_cmd_template.format(p))
                rm_cmd = full_remote_path.apply(lambda p: rm_cmd_template.format(p))

                file_triggers = [
                    cat_cmd.apply(lambda c: hashlib.sha256(c.encode("utf-8")).hexdigest()),
                    data_output.apply(
                        lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()
                    ),
                ]
                all_triggers.extend(file_triggers)

                if props["simulate"]:
                    os.makedirs(props["tmpdir"], exist_ok=True)
                    tmpfile = sub_resource_name.apply(
                        lambda r: os.path.normpath(os.path.join(props["tmpdir"], r))
                    )

                    _ = pulumi.Output.all(sub_resource_name, tmpfile, data_output).apply(
                        lambda args: command.local.Command(
                            args[0],
                            create=cat_cmd_template.format(args[1]),
                            update=cat_cmd_template.format(args[1]),
                            delete=rm_cmd_template.format(args[1]),
                            stdin=args[2],
                            triggers=file_triggers,
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
                else:
                    _ = pulumi.Output.all(
                        sub_resource_name, cat_cmd, rm_cmd, data_output
                    ).apply(
                        lambda args: command.remote.Command(
                            args[0],
                            connection=command.remote.ConnectionArgs(
                                host=props["host"],
                                port=props["port"],
                                user=props["user"],
                                private_key=props["sshkey"].private_key_openssh,
                            ),
                            create=args[1],
                            update=args[1],
                            delete=args[2],
                            stdin=args[3],
                            triggers=file_triggers,
                            logging=RemoteLogging.NONE,
                            opts=pulumi.ResourceOptions(parent=self),
                        )
                    )
            return all_triggers

        files_output = pulumi.Output.from_input(props["files"])
        all_triggers_output = files_output.apply(create_resources_and_get_triggers)
        self.deployment_hash = all_triggers_output.apply(
            lambda list_of_outputs: pulumi.Output.all(*list_of_outputs).apply(
                lambda resolved_triggers: hashlib.sha256(
                    ",".join(sorted(resolved_triggers)).encode("utf-8")
                ).hexdigest()
            )
        )
        self.register_outputs({})


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
    """Copies files from the local machine to a remote host over SSH.

    This function creates an `SSHPut` component to manage the file transfer.

    Args:
        prefix (str):
            A prefix for the resource name.
        host (pulumi.Input[str]):
            The hostname or IP address of the remote host.
        user (pulumi.Input[str]):
            The username to connect with.
        files (dict, optional):
            A dictionary mapping remote file paths to local file paths. Defaults to {}.
        remote_prefix (str, optional):
            A prefix to add to all remote paths. Defaults to "".
        local_prefix (str, optional):
            A prefix to add to all local paths. Defaults to "".
        port (int, optional):
            The SSH port. Defaults to 22.
        delete (bool, optional):
            Whether to delete the remote files when the resource is destroyed. Defaults to False.
        simulate (bool, optional):
            Whether to simulate the file transfer. If None, it is determined by the stack name.
            Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        SSHPut: An `SSHPut` component with a `deployment_hash` attribute.
            The `deployment_hash` attribute is a has string of all filenames and file hashes.
            It can be used for triggering another function if any file changed.

    Example:
    ```python
    config_copied = ssh_put(resource_name, host, user, files=files_dict)
    config_activated = ssh_execute(resource_name, host, user, cmdline=cmdline,
        triggers=[config_copied.deployment_hash],
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
        "tmpdir": os.path.join(project_dir, "build", "tmp", stack_name),
    }
    transferred = SSHPut(prefix, props, opts=opts)
    return transferred


def ssh_get(
    prefix,
    host,
    user,
    files={},
    remote_prefix="",
    local_prefix="",
    port=22,
    delete=False,
    simulate=None,
    local_dir="",
    opts=None,
):
    """Copies files from a remote host to the local machine over SSH.

    This function creates an `SSHGet` component to manage the file transfer

    Args:
        prefix (str):
            A prefix for the resource name.
        host (pulumi.Input[str]):
            The hostname or IP address of the remote host.
        user (pulumi.Input[str]):
            The username to connect with.
        files (dict, optional):
            A dictionary mapping remote file paths to local file paths. Defaults to {}.
            The local file path is prefixed with
        remote_prefix (str, optional):
            A prefix to add to all remote paths. Defaults to "".
        local_prefix (str, optional):
            A prefix to add to all local paths. Defaults to "".
        port (int, optional):
            The SSH port. Defaults to 22.
        delete (bool, optional):
            Whether to delete the local files when the resource is destroyed. Defaults to False.
        simulate (bool, optional):
            Whether to simulate the file transfer. If None, it is determined by the stack name.
            Defaults to None.
        local_dir (str, optional):
            Defaults to `os.path.join(project_dir, "build", "tmp", stack_name)` if empty.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        SSHGet: An `SSHGet` component with a `deployment_hash` attribute.
            The `deployment_hash` attribute is a has string of all filenames and file hashes.
            It can be used for triggering another function if any file changed.
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
        "local_dir": local_dir
        if local_dir
        else os.path.join(project_dir, "build", "tmp", stack_name),
    }
    transferred = SSHGet(prefix, props, opts=opts)
    return transferred


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
    """Deploys string data as files to a remote host over SSH.

    This function creates an `SSHDeploy` component to manage the file
    deployment.

    Args:
        prefix (str):
            A prefix for the resource name.
        host (pulumi.Input[str]):
            The hostname or IP address of the remote host.
        user (pulumi.Input[str]):
            The username to connect with.
        files (dict, optional):
            A dictionary mapping remote file paths to string data. Defaults to {}.
        remote_prefix (str, optional):
            A prefix to add to all remote paths. Defaults to "".
        port (int, optional):
            The SSH port. Defaults to 22.
        secret (bool, optional):
            Whether the file content is a secret. Defaults to False.
        delete (bool, optional):
            Whether to delete the remote files when the resource is destroyed. Defaults to False.
        simulate (bool, optional):
            Whether to simulate the file deployment. If None, it is determined by the stack name.
            Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        SSHDeploy: An `SSHDeploy` component with a `deployment_hash` attribute.
            The `deployment_hash` attribute is a has string of all filenames and file hashes.
            It can be used for triggering another function if any file changed.

    Example:
    ```python
    config_deployed = ssh_deploy(resource_name, host, user, files=config_dict)
    config_activated = ssh_execute(resource_name, host, user, cmdline=cmdline,
        triggers=[config_deployed.deployment_hash],
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
        "tmpdir": os.path.join(project_dir, "build", "tmp", stack_name),
    }
    deployed = SSHDeploy(prefix, props, opts=opts)
    return deployed


class SSHExecute(pulumi.ComponentResource):
    """A Pulumi component for executing a command on a remote host."""

    def __init__(self, resource_name, props, opts=None):
        """Initializes an SSHExecute component.

        Args:
            resource_name (str):
                The name of the resource.
            props (dict):
                A dictionary of properties for the component.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:SSHExecute", resource_name, None, opts)

        if props["simulate"]:
            tmpdir = props["tmpdir"]
            os.makedirs(tmpdir, exist_ok=True)
            # XXX write out environment if not empty on simulate, so we can look what env was set
            if props["environment"] != {}:
                cmdline = (
                    "\n".join(
                        ["{k}={v}".format(k=k, v=v) for k, v in props["environment"].items()]
                    )
                    + "\n"
                    + props["cmdline"]
                )
            else:
                cmdline = props["cmdline"]
            self.executed = command.local.Command(
                resource_name,
                create="cat - > {}".format(os.path.join(tmpdir, resource_name)),
                delete="rm {} || true".format(os.path.join(tmpdir, resource_name)),
                stdin=cmdline,
                triggers=props["triggers"],
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            self.executed = command.remote.Command(
                resource_name,
                connection=command.remote.ConnectionArgs(
                    host=props["host"],
                    port=props["port"],
                    user=props["user"],
                    private_key=props["sshkey"].private_key_openssh,
                ),
                create=props["cmdline"],
                triggers=props["triggers"],
                environment=props["environment"],
                logging=RemoteLogging.NONE,
                opts=pulumi.ResourceOptions(parent=self),
            )
        self.result = self.executed
        self.register_outputs({})


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
    """Executes a command on a remote host over SSH.

    This function uses the `pulumi_command` provider to execute a command on a
    remote host.

    Args:
        prefix (str):
            A prefix for the resource name.
        host (pulumi.Input[str]):
            The hostname or IP address of the remote host.
        user (pulumi.Input[str]):
            The username to connect with.
        cmdline (pulumi.Input[str]):
            The command to execute.
        environment (dict, optional):
            A dictionary of environment variables to set for the command. Defaults to {}.
        port (int, optional):
            The SSH port. Defaults to 22.
        simulate (bool, optional):
            Whether to simulate the command execution. If None, it is determined by the stack
            name. Defaults to None.
        triggers (list, optional):
            A list of triggers to re-run the command. Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        SSHExecute:
            The command resource.
    """

    from .authority import ssh_factory

    resource_name = "{}_ssh_execute".format(prefix)
    stack_name = pulumi.get_stack()
    props = {
        "host": host,
        "port": port,
        "user": user,
        "cmdline": cmdline,
        "sshkey": ssh_factory.provision_key,
        "environment": environment,
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "build", "tmp", stack_name),
        "triggers": triggers,
    }
    executed = SSHExecute(resource_name, props, opts=opts)
    return executed


class DataExport(pulumi.ComponentResource):
    """A Pulumi component for exporting data to a local file.

    This component writes data to a local file, with optional encryption using
    `age`. It is used by the `public_local_export` and `encrypted_local_export`
    functions.

    returns:
        self.filename
    """

    def __init__(
        self,
        prefix,
        filename,
        data,
        key=None,
        filter="",
        delete=False,
        triggers=None,
        opts=None,
    ):
        """Initializes a DataExport component.

        Args:
            prefix (str):
                A prefix for the resource name and directory.
            filename (str):
                The name of the file to export.
            data (pulumi.Input[str]):
                The data to export.
            key (pulumi.Input[str], optional):
                The public key to use for `age` encryption. Defaults to None.
            filter (str, optional):
                A shell command to pipe the data through. Defaults to "".
            delete (bool, optional):
                Whether to delete the file when the resource is destroyed. Defaults to False.
            triggers (list, optional):
                A list of triggers to re-run the export. Defaults to None.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:DataExport", "_".join([prefix, filename]), None, opts)

        stack_name = pulumi.get_stack()
        filter += " | " if filter else ""

        if key:
            self.filename = os.path.join(
                project_dir, "state", "files", stack_name, prefix, "{}.age".format(filename)
            )
            create_cmd = pulumi.Output.concat(
                "mkdir -p ",
                os.path.dirname(self.filename),
                " && ",
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
            create_cmd = pulumi.Output.concat(
                "mkdir -p ",
                os.path.dirname(self.filename),
                " && ",
                filter,
                "cat - > ",
                self.filename,
            )

        resource_name = "{}_{}local_storage_{}".format(
            prefix,
            "public_" if not key else "",
            os.path.basename(self.filename).replace("/", "_"),
        )
        delete_cmd = "rm {} | true".format(self.filename) if delete else ""

        if triggers:
            # If optional triggers are provided, use them and ignore stdin
            final_triggers = triggers + [self.filename]
            ignore_opts = pulumi.ResourceOptions(ignore_changes=["stdin"])
            final_opts = (
                pulumi.ResourceOptions.merge(opts, ignore_opts) if opts else ignore_opts
            )
        else:
            # data is assumed stable, hash it for the trigger
            final_triggers = [
                data.apply(lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()),
                self.filename,
            ]
            final_opts = opts

        self.saved = command.local.Command(
            resource_name,
            create=create_cmd,
            update=create_cmd,
            delete=delete_cmd,
            dir=project_dir,
            stdin=data,
            # DONT log output, as this might be security sensitive
            logging=LocalLogging.NONE,
            triggers=final_triggers,
            opts=final_opts,
        )
        self.register_outputs({})


def encrypted_local_export(
    prefix, filename, data, filter="", delete=False, triggers=None, opts=None
):
    """Exports and encrypts data to a local file using `age`.

    This function creates a `DataExport` component to write data to a local
    file, encrypting it with `age` using the project's authorized SSH keys.

    Args:
        prefix (str):
            A prefix for the resource name and directory.
        filename (str):
            The name of the file to export.
        data (pulumi.Input[str]):
            The data to export.
        filter (str, optional):
            A shell command to pipe the data through before encryption. Defaults to "".
        delete (bool, optional):
            Whether to delete the file when the resource is destroyed. Defaults to False.
        triggers (list, optional):
            A list of triggers to re-run the export. Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        DataExport:
            A `DataExport` component.
    """

    from .authority import ssh_factory

    return DataExport(
        prefix,
        filename,
        data,
        ssh_factory.authorized_keys,
        filter=filter,
        delete=delete,
        triggers=triggers,
        opts=opts,
    )


def public_local_export(
    prefix, filename, data, filter="", delete=False, triggers=None, opts=None
):
    """Exports data to a local file without encryption.

    This function creates a `DataExport` component to write data to a local
    file.

    Args:
        prefix (str):
            A prefix for the resource name and directory.
        filename (str):
            The name of the file to export.
        data (pulumi.Input[str]):
            The data to export.
        filter (str, optional):
            A shell command to pipe the data through. Defaults to "".
        delete (bool, optional):
            Whether to delete the file when the resource is destroyed. Defaults to False.
        triggers (list, optional):
            A list of triggers to re-run the export. Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        DataExport:
            A `DataExport` component.
    """

    return DataExport(
        prefix,
        filename,
        data,
        filter=filter,
        delete=delete,
        triggers=triggers,
        opts=opts,
    )


def salt_config(resource_name, stack_name, base_dir):
    """Generates a SaltStack minion configuration.

    This function creates a configuration dictionary for a SaltStack minion,
    including paths for SLS files, pillars, and other directories.

    Grains available:
      - resource_name, base_dir, root_dir, tmp_dir, sls_dir, pillar_dir

    Args:
        resource_name (str):
            The name of the resource, used for directory names.
        stack_name (str):
            The name of the Pulumi stack.
        base_dir (str):
            The base directory for the SaltStack configuration.

    Returns:
        dict:
            A dictionary representing the SaltStack minion configuration.
    """

    root_dir = os.path.join(base_dir, "build", "salt", stack_name, resource_name)
    tmp_dir = os.path.join(base_dir, "build", "tmp", stack_name, resource_name)
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
    """A Pulumi component for executing a local SaltStack call.

    This component configures and runs a `salt-call` command on the local
    machine. It sets up the necessary directories and configuration files for
    the SaltStack execution.

    - sls_dir defaults to project_dir
    - config/run/tmp/cache and other files default to build/salt/stackname/resource_name
    - grains from salt_config available
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
        """Initializes a LocalSaltCall component.

        Args:
            resource_name (str):
                The name of the resource.
            *args:
                Arguments to pass to the `salt-call` command.
            pillar (dict, optional):
                A dictionary to use for the saltstack pillar data. Defaults to {}.
            environment (dict, optional):
                A dictionary of environment variables available in saltstack. Can be used to pass secrets. Defaults to {}.
            sls_dir (str, optional):
                The directory containing the SLS files. Defaults to the project directory.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
            **kwargs:
                Additional arguments to pass to the `command.local.Command`.
        """
        super().__init__("pkg:tools:LocalSaltCall", resource_name, None, opts)
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
            _ = m.write(yaml.safe_dump(self.config))
        with open(os.path.join(pillar_dir, "top.sls"), "w") as m:
            _ = m.write("base:\n  '*':\n    - main\n")
        with open(os.path.join(pillar_dir, "main.sls"), "w") as m:
            _ = m.write(yaml.safe_dump(pillar))

        self.executed = command.local.Command(
            resource_name,
            create="{sys_prefix}/bin/python {scripts_dir}/salt_execute.py -c {conf_dir} {args}".format(
                sys_prefix=sys.prefix,
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
    """A Pulumi component for executing a SaltStack call on a remote host.

    This component deploys the necessary SaltStack configuration and SLS files
    to a remote host, and then executes a `salt-call` command.

    - grains from salt_config available
    - NOTE: function replaces parameters "{{base_dir}}" and "{{args}}" in the "exec" string
        - therefore avoid (rename) shell vars named "${{base_dir}}" or "${{args}}"
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
        """Initializes a RemoteSaltCall component.

        Args:
            resource_name (str):
                The name of the resource.
            host (pulumi.Input[str]):
                The hostname or IP address of the remote host.
            user (pulumi.Input[str]):
                The username to connect with.
            base_dir (str):
                The base directory on the remote host for the SaltStack configuration.
            *args:
                Arguments to pass to the `salt-call` command.
            pillar (dict, optional):
                A dictionary to use as pillar data. Defaults to {}.
            salt (str, optional):
                The content of the main SLS file. Defaults to "".
            environment (dict, optional):
                A dictionary of environment variables for the command. Defaults to {}.
            root_dir (str, optional):
                The root directory for the SaltStack minion. Defaults to a path within
                `base_dir`.
            tmp_dir (str, optional):
                The temporary directory for the SaltStack minion. Defaults to a path
                within `base_dir`.
            sls_dir (str, optional):
                The directory for SLS files. Defaults to a path within `root_dir`.
            exec (str, optional):
                The command to execute. Defaults to "/usr/bin/salt-call -c {base_dir} {args}".
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
            **kwargs:
                Additional arguments to pass to the `ssh_execute` function.
        """
        super().__init__(
            "pkg:tools:RemoteSaltCall",
            "{}_{}".format(resource_name, user),
            None,
            opts,
        )

        stack = pulumi.get_stack()
        self.config = salt_config(resource_name, stack, base_dir)
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


class BuildFromSalt(pulumi.ComponentResource):
    """Executes a local SaltStack call to build an image or other content.

    It passes a merged configuration from pillar and pulumi config object to the saltstack state.
    Use pulumi config object `build` `{"debug": True}` to let salt-call output debug log.

    The build is triggered when the configuration or environment changes.
    """

    def __init__(
        self,
        resource_name,
        sls_name,
        pillar={},
        environment={},
        sls_dir=None,
        pillar_key="",
        pulumi_key="",
        debug_output=False,
        opts=None,
    ):
        """
        Args:
            resource_name (str):
                The name of the Pulumi resource.
            sls_name (str):
                The name of the Salt state (SLS) file to execute.
            pillar (dict, optional, defaults to "{}"):
                A dictionary to use for the saltstack pillar data.
            environment (dict, optional, defaults to "{}"):
                A dictionary of environment variables available in saltstack.
                Can be used to pass secrets. values can be string of pulumi output objects.
            sls_dir (str, optional, defaults to the project directory):
                The directory containing the SLS files.
            pillar_key (str, optional, defaults to ""):
            pulumi_key (str, optional, defaults to ""):
                if both set, pulumi_key is used to get a pulumi config object,
                that will get merged with pillar at pillar_key
            debug_output (boolean, optional, defaults to "False"):
            opts (pulumi.ResourceOptions, optional, defaults to "None"):
                The options for the resource.
        Returns:
            .result: a `LocalSaltCall.result` resource representing the Salt execution.
        """
        super().__init__("pkg:tools:BuildFromSalt", resource_name, None, opts)

        config = pulumi.Config("")
        if pillar_key and pulumi_key:
            config_dict = {pillar_key: config.get_object(pulumi_key) or {}}
            merged_pillar = merge_dict_struct(pillar, config_dict)
        else:
            merged_pillar = pillar

        merged_pillar_hash = hashlib.sha256(
            json.dumps(merged_pillar).encode("utf-8")
        ).hexdigest()
        resolved_environment = pulumi.Output.all(**environment)
        environment_hash = resolved_environment.apply(
            lambda env: hashlib.sha256(
                json.dumps(env, sort_keys=True).encode("utf-8")
            ).hexdigest()
        )
        salt_debug = dict_get_bool(config.get_object("build"), ["debug"], False)

        salt_execution = LocalSaltCall(
            resource_name,
            "-l all" if salt_debug else "",
            "state.sls",
            sls_name,
            pillar=merged_pillar,
            environment=environment,
            sls_dir=sls_dir if sls_dir else this_dir,
            triggers=[merged_pillar_hash, environment_hash],
            opts=opts,
        )
        self.result = salt_execution.result


class _TimedResourceProviderInputs:
    """Inputs for the TimedResourceProvider."""

    def __init__(
        self,
        timeout_sec: str,
        creation_type: str,
        base: Optional[str],
        range: Optional[str],
    ):
        """Initializes the inputs for the TimedResourceProvider.

        Args:
            timeout_sec (str):
                The timeout in seconds.
            creation_type (str):
                The type of value to generate.
            base (Optional[str]):
                The base value for `random_int`.
            range (Optional[str]):
                The range for `random_int`.
        """
        self.timeout_sec = timeout_sec
        self.creation_type = creation_type
        self.base = base
        self.range = range


class TimedResourceProvider(pulumi.dynamic.ResourceProvider):
    """A Pulumi dynamic resource provider for the TimedResource.

    This provider implements the logic for creating, reading, updating, and
    deleting `TimedResource` resources.
    """

    def _now(self) -> int:
        """Returns the current time as a Unix timestamp (seconds)."""
        return int(time.time())

    def _generate_value(
        self, creation_type: str, base: Optional[str], range: Optional[str]
    ) -> str:
        """Generates a value based on the creation type."""
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
        """Creates a new TimedResource."""
        value = self._generate_value(
            props["creation_type"], props.get("base"), props.get("range")
        )
        last_updated = self._now()
        return pulumi.dynamic.CreateResult(
            id_=str(uuid.uuid4()),
            outs={"value": str(value), "last_updated": str(last_updated)},
        )

    def read(self, id_: str, props: _TimedResourceProviderInputs) -> pulumi.dynamic.ReadResult:
        """Reads the state of an existing TimedResource."""
        return pulumi.dynamic.ReadResult(id_=id_, outs=props)

    def diff(
        self,
        id_: str,
        old_inputs: Dict[str, Any],
        new_inputs: _TimedResourceProviderInputs,
    ) -> pulumi.dynamic.DiffResult:
        """Checks if the resource needs to be updated.

        Args:
            id_ (str):
                The resource ID.
            old_inputs (Dict[str, Any]):
                The previous input properties.
            new_inputs (_TimedResourceProviderInputs):
                The new input properties.

        Returns:
           pulumi.dynamic.DiffResult:
               A DiffResult indicating if changes are needed and which inputs changed.
        """
        timeout_sec = int(new_inputs["timeout_sec"])
        last_updated = int(old_inputs["last_updated"])
        now = self._now()

        changes = (now - last_updated) > timeout_sec
        return pulumi.dynamic.DiffResult(changes=changes)

    def update(
        self, id_: str, _olds: Dict[str, Any], new_inputs: _TimedResourceProviderInputs
    ) -> pulumi.dynamic.UpdateResult:
        """Updates an existing TimedResource.

        Args:
            id_ (str):
                The resource ID.
            _olds (Dict[str, Any]):
                The previous output properties.
            new_inputs (_TimedResourceProviderInputs):
                The new input properties.

        Returns:
            pulumi.dynamic.UpdateResult:
                The UpdateResult containing the updated output properties.
        """
        value = self._generate_value(
            new_inputs["creation_type"], new_inputs.get("base"), new_inputs.get("range")
        )
        last_updated = self._now()
        return pulumi.dynamic.UpdateResult(
            outs={"value": str(value), "last_updated": str(last_updated)}
        )

    def delete(self, id: str, props: Dict[str, Any]) -> None:
        """Deletes a TimedResource."""
        # pulumi will do the deletion
        pass


class TimedResourceInputs:
    """Input properties for TimedResource."""

    def __init__(
        self,
        timeout_sec: pulumi.Input[int],
        creation_type: pulumi.Input[str],
        base: Optional[pulumi.Input[int]] = None,
        range: Optional[pulumi.Input[int]] = None,
    ):
        """Initializes the inputs for TimedResource.

        Args:
            timeout_sec (pulumi.Input[int]):
                Timeout in seconds the service will be available.
            creation_type (pulumi.Input[str]):
                One of "random_int", "unixtime", "uuid".
            base (Optional[pulumi.Input[int]], optional):
                Base number for random_int. Defaults to None.
            range (Optional[pulumi.Input[int]], optional):
                Range for random_int. Defaults to None.
        """
        self.timeout_sec = timeout_sec
        self.creation_type = creation_type
        self.base = base
        self.range = range


class TimedResource(pulumi.dynamic.Resource):
    """A Pulumi dynamic resource that regenerates its value after a timeout.

    This resource generates a value based on a specified creation type (e.g.,
    random integer, UUID, Unix timestamp) and updates it if a certain amount
    of time has passed since the last update.
    """

    value: pulumi.Output[str]
    last_updated: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        args: TimedResourceInputs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Initializes a TimedResource.

        Args:
            name (str):
                The name of the resource.
            args (TimedResourceInputs):
                The input properties for the resource.
            opts (Optional[pulumi.ResourceOptions], optional):
                The options for the resource. Defaults to None.
        """
        super().__init__(
            TimedResourceProvider(),
            f"{name}_timed_resource",
            {"value": None, "last_updated": None, **vars(args)},
            opts,
        )


class ServePrepare(pulumi.ComponentResource):
    """A Pulumi component for preparing to serve a one-time web resource.

    This component generates a dynamic configuration for a temporary web
    server, including a random port and a unique request path. It can also
    initiate port forwarding.

    Attributes:
        config (pulumi.Output[dict]):
            The final server configuration.
        result (pulumi.Output[str]):
            The final server configuration as a YAML string.
    """

    def __init__(
        self,
        resource_name: str,
        config_str: str = "",
        timeout_sec: int = 150,
        tokenlifetime_sec: int = 10 * 60,
        port_base: int = 47000,
        port_range: int = 3000,
        serve_interface: str = "",
        serve_ip: str = "",
        mtls_clientid: str = "",
        request_header: dict = {},
        opts: pulumi.Input[object] = None,
    ) -> None:
        """Initializes a ServePrepare component.

        Args:
            resource_name (str):
                The name of the resource.
            config_str (str, optional):
                A YAML string to be merged into the default configuration. Defaults to "".
            timeout_sec (int, optional):
                The timeout in seconds for the server. Defaults to 150.
            tokenlifetime_sec (int, optional):
                The lifetime of the generated port and path. Defaults to 600.
            port_base (int, optional):
                The base for the random port number. Defaults to 47000.
            port_range (int, optional):
                The range for the random port number. Defaults to 3000.
            serve_interface (str, optional):
                The network interface to serve on. Defaults to "".
            serve_ip (str, optional):
                The IP address to serve on. Defaults to "".
            mtls_clientid (str, optional):
                The client ID for mTLS. Defaults to "".
            opts (pulumi.Input[object], optional):
                The options for the resource. Defaults to None.
        """
        from .authority import config, ca_factory, provision_host_tls

        super().__init__(
            "pkg:tools:ServeConfigure", "{}_serve_prepare".format(resource_name), None, opts
        )

        # Build the initial static config (*without* Output values)
        self.static_config = {
            "timeout": timeout_sec,
            "mtls": False,
            "mtls_clientid": mtls_clientid if mtls_clientid else "",
            "payload": None,
            "port_forward": config.get_object("port_forward")
            or {"enabled": False, "lifetime_sec": tokenlifetime_sec},
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
            serve_ip, serve_port, request_path, cert, key, ca_cert, rh = args
            merged_config = self.static_config.copy()
            merged_config["request_header"] = rh
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
            pulumi.Output.from_input(request_header),
        ).apply(build_merged_config)

        if self.merged_config["port_forward"]["enabled"] and False:
            # if enabled, run port_forward and update config with returned port_forward values
            self.forward = command.local.Command(
                resource_name + "_forward",
                create=f"python {os.path.join(this_dir, 'scripts/port_forward.py')}"
                + " --yaml-from-stdin --yaml-to-stdout",
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
    """A Pulumi component for serving a one-time, secure web resource.

    This component starts a temporary web server that serves a given payload
    and shuts down after the first request.

    Attributes:
        result (pulumi.Output[str]):
            The standard output of the server script, which may contain information
            from the request.
    """

    def __init__(self, resource_name, config, payload, opts=None):
        """Initializes a ServeOnce component.

        Args:
            resource_name (str):
                The name of the resource.
            config (pulumi.Input[dict]):
                The configuration for the server.
            payload (pulumi.Input[str]):
                The payload to serve.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__(
            "pkg:tools:ServeOnce", "{}_serve_once".format(resource_name), None, opts
        )

        def merge_func(args):
            payload_value = args[0]
            config_value = args[1]
            return {**config_value, "payload": payload_value}

        # Ensure both inputs are resolved before merging
        this_config = pulumi.Output.all(payload, config).apply(merge_func)
        this_opts = ResourceOptions.merge(
            ResourceOptions(parent=self, additional_secret_outputs=["stdout"]),
            opts,
        )
        self.executed = command.local.Command(
            "{}_serve_once".format(resource_name),
            create=f"python {os.path.join(this_dir, 'scripts/serve_once.py')}"
            + " --verbose --yes",
            stdin=this_config.apply(yaml.safe_dump),
            opts=this_opts,
        )
        self.result = self.executed.stdout
        self.register_outputs({})


def serve_simple(resource_name, yaml_str, opts=None):
    """Serves a one-time web resource with a simple configuration.

    This function is a simplified wrapper around `ServePrepare` and `ServeOnce`
    for common use cases.

    Args:
        resource_name (str):
            The name of the resource.
        yaml_str (str):
            The YAML payload to serve.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        ServeOnce:
            A `ServeOnce` component.
    """
    this_config = ServePrepare(resource_name, config_str="", opts=opts)
    return ServeOnce(resource_name, this_config.config, yaml.safe_load(yaml_str), opts=opts)


class WriteRemovable(pulumi.ComponentResource):
    """A Pulumi component for writing an image to a removable storage device."""

    def __init__(self, resource_name, image, serial, size=0, patches=None, opts=None):
        """Initializes a WriteRemovable component.

        Args:
            resource_name (str):
                The name of the resource.
            image (pulumi.Input[str]):
                The path to the image file to write.
            serial (pulumi.Input[str]):
                The serial number of the target device.
            size (pulumi.Input[int], optional):
                The expected size of the device. Defaults to 0.
            patches (list, optional):
                A list of patches to apply to the image. Defaults to None.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        super().__init__("pkg:tools:WriteRemovable", resource_name, None, opts)

        create_str = (
            "python "
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
        self.result = self.executed
        self.register_outputs({})


def write_removable(resource_name, image, serial, size=0, patches=None, opts=None):
    """Writes an image to a removable storage device.

    This function is a wrapper around the `WriteRemovable` component.

    Args:
        resource_name (str):
            The name of the resource.
        image (pulumi.Input[str]):
            The path to the image file to write.
        serial (pulumi.Input[str]):
            The serial number of the target device.
        size (pulumi.Input[int], optional):
            The expected size of the device. Defaults to 0.
        patches (list, optional):
            A list of patches to apply to the image. Defaults to None.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        WriteRemovable:
            A `WriteRemovable` component.
    """
    return WriteRemovable(
        "write_removable_{}".format(resource_name),
        image=image,
        serial=serial,
        size=size,
        patches=patches,
        opts=opts,
    )


class WaitForHostReadyProvider(pulumi.dynamic.ResourceProvider):
    """A Pulumi dynamic resource provider for waiting for a host to be ready."""

    def create(self, props):
        """Creates the WaitForHostReady resource.

        This method is called when the resource is created. It attempts to
        connect to the host and check for the file until the timeout is
        reached.

        Args:
            props (dict):
                The properties for the resource.

        Returns:
            pulumi.dynamic.CreateResult:
                The result of the create operation.

        Raises:
            Exception:
                If the host is not ready within the timeout.
        """
        import paramiko
        import time

        name = props["name"]
        host = props["host"]
        port = int(props["port"])
        user = props["user"]
        private_key_pem = props["private_key"]
        isready_cmd = props["isready_cmd"]
        timeout = props["timeout"]
        connect_timeout = props["connect_timeout"]
        retry_delay = props["retry_delay"]

        try:
            pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(private_key_pem))
        except Exception as ed_e:
            print(
                f"Failed to parse as Ed25519Key ({type(ed_e).__name__}: {ed_e}), trying RSAKey..."
            )
            try:
                pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_pem))
            except Exception as rsa_e:
                print(
                    f"Failed to parse as RSAKey ({type(rsa_e).__name__}: {rsa_e}). Both types failed."
                )
                raise Exception(
                    f"Failed to parse private key. Tried Ed25519 (failed: {ed_e}) and RSA (failed: {rsa_e})"
                )

        last_exception_message = ""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, port=port, username=user, pkey=pkey, timeout=connect_timeout)
                print(f"Connected {user}@{host}:{port}")

                stdin, stdout, stderr = ssh.exec_command(isready_cmd)
                exit_status = stdout.channel.recv_exit_status()
                ssh.close()

                if exit_status == 0:
                    print(
                        f"{name} host is ready. isready_cmd '{isready_cmd}' returned success"
                    )
                    return pulumi.dynamic.CreateResult(id_=str(uuid.uuid4()), outs={})
                else:
                    print(
                        f"Warning: isready_cmd '{isready_cmd}' failed with error: {exit_status}"
                    )
                    time.sleep(retry_delay)
            except Exception as e:
                last_exception_message = str(e)
                if isinstance(e, (EOFError, paramiko.SSHException)) or (
                    hasattr(e, "errno") and e.errno is None
                ):
                    print(f"{name} waiting ({time.time() - start_time:.2f}s)")
                else:
                    print(f"Exception while waiting ({time.time() - start_time:.2f}s): {e}")
                time.sleep(retry_delay)

        # If the loop times out, raise an exception with the last meaningful error
        if last_exception_message:
            raise Exception(
                f"Timeout waiting for host {host} to be connectable and/or isready_cmd failed. Last error: {last_exception_message}"
            )
        else:
            raise Exception(
                f"Timeout waiting for host {host} to be connectable and/or isready_cmd failed."
            )


class WaitForHostReady(pulumi.dynamic.Resource):
    """A Pulumi dynamic resource that waits for a remote host to be ready."""

    def __init__(
        self,
        name,
        host,
        user,
        isready_cmd,
        private_key,
        port=22,
        timeout=450,
        connect_timeout=15,
        retry_delay=5,
        opts=None,
    ):
        """Initializes a WaitForHostReady resource.

        Args:
            name (str):
                The name of the resource.
            host (pulumi.Input[str]):
                The hostname or IP address of the remote host.
            user (pulumi.Input[str]):
                The username to connect with.
            isready_cmd (pulumi.Input[str]):
                The command executed on the target host, that if host is ready will exit 0, and 1 if otherwise.
            private_key (pulumi.Input[str]):
                The private key for SSH authentication.
            port (int, optional):
                The SSH port. Defaults to 22.
            timeout (int, optional):
                The timeout in seconds. Defaults to 300.
            connect_timeout (int, optional)
                The connect timeout in seconds. Defaults to 15.
            retry_delay (int, optional)
                The retry delay in seconds between connect tries. Defaults to 5.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
        """
        name = f"{name}_wait_for_host_ready"
        super().__init__(
            WaitForHostReadyProvider(),
            name,
            {
                "name": name,
                "host": host,
                "port": port,
                "user": user,
                "private_key": private_key,
                "isready_cmd": isready_cmd,
                "timeout": timeout,
                "connect_timeout": connect_timeout,
                "retry_delay": retry_delay,
            },
            opts,
        )
