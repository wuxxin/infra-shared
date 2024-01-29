#!/usr/bin/env python
"""
## Pulumi - Tools

- pulumi tools library, can also be used as command line utility:
    - `pipenv $0 [--stack sim] library function *stringargs`

### Pulumi Functions
- serve_prepare
- serve_once
- serve_simple

- ssh_copy
- ssh_deploy
- ssh_execute

- write_removeable
- encrypted_local_export
- public_local_export

- log_warn

### Pulumi Components
- LocalSaltCall
- RemoteSaltCall

### Pulumi Resources
- TimedResource

### Python
- join_paths
- sha256sum_file
- get_default_host_ip

"""

import copy
import hashlib
import os
import random
import socket
import sys
import time

import pulumi
import pulumi_command as command
import yaml

from pulumi.dynamic import Resource, ResourceProvider, CreateResult, UpdateResult


this_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(this_dir, ".."))


def log_warn(x):
    "write str(var) to pulumi.log.warn with line numbering, to be used as var.apply(log_warn)"
    pulumi.log.warn(
        "\n".join(
            [
                "{}:{}".format(nr + 1, line)
                for nr, line in enumerate(str(x).splitlines())
            ]
        )
    )


def join_paths(basedir, *filepaths):
    "combine filepaths with basedir like os.path.join, but remove leading '/' of each filepath"
    filepaths = [path[1:] if path.startswith("/") else path for path in filepaths]
    return os.path.join(basedir, *filepaths)


def sha256sum_file(filename):
    "sha256sum of file, logically backported from python 3.11"

    h = hashlib.sha256()
    buf = bytearray(2**18)
    view = memoryview(buf)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(view):
            h.update(view[:n])
    return h.hexdigest()


def get_default_host_ip():
    "return ip of host connected to the outside, or None if not found"
    try:
        gateway_addr = socket.gethostbyname(socket.gethostname())
        if (
            not socket.inet_pton(socket.AF_INET, gateway_addr)
            or gateway_addr.startswith("127.")
            or gateway_addr.startswith("::1")
        ):
            gateway_addr = None
    except socket.gaierror:
        gateway_addr = None
    return gateway_addr


class SSHCopier(pulumi.ComponentResource):
    """Pulumi Component: use with function ssh_copy()"""

    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHCopier", name, None, opts)

        self.props = props
        self.triggers = []
        for key, value in self.props["files"].items():
            setattr(self, key, self.__transfer(name, key, value))
        self.register_outputs({})

    def __transfer(self, name, remote_path, local_path):
        resource_name = "copy_{}".format(remote_path.replace("/", "_"))
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
        triggers = [
            hashlib.sha256(full_remote_path.encode("utf-8")).hexdigest(),
            pulumi.Output.concat(sha256sum_file(local_path)),
        ]
        self.triggers.extend(triggers)

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            copy_cmd = "cp {} {}"
            rm_cmd = "rm {} || true" if self.props["delete"] else ""

            file_transfered = command.local.Command(
                resource_name,
                create=copy_cmd.format(local_path, tmpfile),
                delete=rm_cmd.format(tmpfile),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            file_transfered = command.remote.CopyFile(
                resource_name,
                local_path=local_path,
                remote_path=full_remote_path,
                connection=command.remote.ConnectionArgs(
                    host=self.props["host"],
                    port=self.props["port"],
                    user=self.props["user"],
                    private_key=self.props["sshkey"].private_key_openssh.apply(
                        lambda x: x
                    ),
                ),
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
        resource_name = "deploy_{}".format(remote_path.replace("/", "_"))
        cat_cmd = (
            'x="{}" && mkdir -p $(dirname "$x") && umask 066 && cat - > "$x"'
            if self.props["secret"]
            else 'x="{}" && mkdir -p $(dirname "$x") && cat - > "$x"'
        )
        rm_cmd = "rm {} || true" if self.props["delete"] else ""
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
        triggers = [
            hashlib.sha256(
                cat_cmd.format(full_remote_path).encode("utf-8")
            ).hexdigest(),
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
                    private_key=self.props["sshkey"].private_key_openssh.apply(
                        lambda x: x
                    ),
                ),
                create=cat_cmd.format(full_remote_path),
                update=cat_cmd.format(full_remote_path),
                delete=rm_cmd.format(full_remote_path),
                stdin=data.apply(lambda x: str(x)),
                triggers=triggers,
                opts=pulumi.ResourceOptions(parent=self),
            )
        return value_deployed


def ssh_copy(
    prefix,
    host,
    user,
    files={},
    port=22,
    delete=False,
    remote_prefix="",
    simulate=None,
    opts=None,
):
    """copy a set of files from localhost to ssh target using ssh/sftp

    if simulate==True: files are not transfered but written out to state/tmp/stack_name
    if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    files= {remotepath: localpath,}

    #### Returns
    - [attr(remotepath, remote.CopyFile|local.Command) for remotepath in files]
    - triggers: list of key and data hashes for every file
        - can be used for triggering another function if any file changed

    #### Example
    ```python
    config_copied = ssh_copy(resource_name, host, user, files=files_dict)
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
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    transfered = SSHCopier(prefix, props, opts=opts)
    # pulumi.export("{}_copy".format(prefix), transfered)
    return transfered


def ssh_deploy(
    prefix,
    host,
    user,
    files={},
    port=22,
    secret=False,
    delete=False,
    remote_prefix="",
    simulate=None,
    opts=None,
):
    """deploy a set of strings as small files to a ssh target

    if simulate==True: data is not transfered but written out to state/tmp/stack_name
    if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    files: {remotepath: data,}

    #### Returns
    - [attr(remotepath, remote.Command|local.Command) for remotepath in files]
    - triggers: list of key and data hashes for every file,
        - can be used for triggering another function if any file changed

    #### Example:
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
        "sshkey": ssh_factory.provision_key,
        "secret": secret,
        "delete": delete,
        "remote_prefix": remote_prefix,
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
    port=22,
    simulate=None,
    triggers=None,
    environment={},
    opts=None,
):
    """execute a command as user on a ssh target host

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
                private_key=ssh_factory.provision_key.private_key_openssh.apply(
                    lambda x: x
                ),
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

    def __init__(
        self, prefix, filename, data, key=None, filter="", delete=False, opts=None
    ):
        super().__init__("pkg:index:DataExport", prefix, None, opts)

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
                data.apply(
                    lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()
                ),
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


def salt_config(
    resource_name, stack_name, base_dir, root_dir=None, tmp_dir=None, sls_dir=None
):
    """generate a saltstack salt config

    - sls_dir defaults to base_dir
    - grains available
      - resource_name, base_dir, root_dir, tmp_dir, sls_dir, pillar_dir

    """

    root_dir = root_dir or os.path.join(
        base_dir, "state", "salt", stack_name, resource_name
    )
    tmp_dir = tmp_dir or os.path.join(
        base_dir, "state", "tmp", stack_name, resource_name
    )
    sls_dir = sls_dir if sls_dir else base_dir
    pillar_dir = os.path.join(root_dir, "pillar")

    config = yaml.safe_load(
        """
id: {resource_name}
local: True
log_level_logfile: info
file_client: local
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
log_file: {root_dir}/var/log/salt/minion

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
    - config/run/tmp/cache and other files default to state/salt/stackname
    - grains from salt_config available

    #### Example: build openwrt image
    ```python
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
        self.config = salt_config(resource_name, stack, project_dir, sls_dir=sls_dir)
        pillar_dir = self.config["grains"]["pillar_dir"]

        os.makedirs(self.config["root_dir"], exist_ok=True)
        os.makedirs(pillar_dir, exist_ok=True)

        with open(self.config["conf_file"], "w") as m:
            m.write(yaml.safe_dump(self.config))
        with open(os.path.join(pillar_dir, "top.sls"), "w") as m:
            m.write("base:\n  '*':\n    - main\n")
        with open(os.path.join(pillar_dir, "main.sls"), "w") as m:
            m.write(yaml.safe_dump(pillar))

        self.executed = command.local.Command(
            resource_name,
            create="pipenv run salt-call -c {conf_dir} {args}".format(
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
            os.path.relpath(
                self.config["conf_file"], base_dir
            ): pulumi.Output.from_input(yaml.safe_dump(self.config)),
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


class TimedResourceProvider(ResourceProvider):
    """resource provider for TimedResource"""

    def create(self, props):
        # Call the user-defined creation function to get a new value
        new_value = props["creation_fn"]()
        # Capture the current timestamp
        current_time = int(time.time())
        # The unique ID for the resource is just its timestamp for simplicity
        return CreateResult(
            current_time, {"value": new_value, "timestamp": current_time}
        )

    def update(self, id, _olds, _news):
        # Recompute the current timestamp and check against the specified timeout
        current_time = int(time.time())
        if current_time - _olds["timestamp"] > _news["timeout_sec"]:
            # If the timeout has passed, call the creation function again
            new_value = _news["creation_fn"]()
            return UpdateResult({"value": new_value, "timestamp": current_time})
        return None  # No changes if the timeout has not passed

    def diff(self, id, _olds, _news):
        # Determine if an update is needed based on the timeout
        current_time = int(time.time())
        if current_time - _olds["timestamp"] > _news["timeout_sec"]:
            # If the timeout has passed, signal that an update is needed
            return pulumi.DiffResult(changes=True)
        # Otherwise, no update is needed
        return pulumi.DiffResult(changes=False)


class TimedResource(Resource):
    """A custom resource that regenerates a value based on the provided function if timeout passed

    :param str name: Name of the resource.
    :param function creation_fn: A function that regenerates a new value string
    :param int timeout_sec: Timeout in seconds to trigger regeneration

    Usage:
    ```python
    my_res = TimedResource("my-random-number", timeout_sec=10,
        creation_fn=lambda x: str(random.randint(30000,32000))
    )
    current_number= my_res.output["value"].apply(lambda v: int(v))
    ```
    """

    def __init__(self, name, creation_fn, timeout_sec, opts=None):
        super().__init__(
            TimedResourceProvider(),
            name,
            {
                "value": None,
                "timestamp": None,
                "creation_fn": creation_fn,
                "timeout_sec": timeout_sec,
            },
            opts,
        )


class ServePrepare(pulumi.ComponentResource):
    """a serve-prepare component to configure a future available web resource

    :param str config_input: yaml input added on top of the default resource config
    :param int timeout_sec: timeout in seconds the service will be available
    :param int port_base: base port number of the web resource
    :param int port_range: range of ports for the web resource

    It creates a `TimedResource` object to manage the local port configuration
        and initializes port forwarding to the local port if requested.
    """

    def __init__(
        self,
        resource_name: str,
        config_input: str = "",
        timeout_sec: int = 45,
        port_base: int = 47000,
        port_range: int = 3000,
        opts: pulumi.Input[object] = None,
    ) -> None:
        from .authority import config, ca_factory, provision_host_tls

        super().__init__("pkg:index:ServeConfigure", resource_name, None, opts)

        forward_config = config.get_object("port_forward", {"enabled": False})

        self.local_port_config = TimedResource(
            "local-port-config",
            creation_fn=lambda: str(random.randint(port_base, port_base + port_range)),
            timeout_sec=timeout_sec,
            opts=pulumi.ResourceOptions(parent=self),
        )
        serve_port = self.local_port_config.output["value"].apply(lambda v: int(v))

        self.config = {
            "serve_port": serve_port,
            "timeout": timeout_sec,
            "cert": provision_host_tls.chain,
            "key": provision_host_tls.key.private_key_pem,
            "ca_cert": ca_factory.root_cert_pem,
            "mtls": True,
            "payload": None,
            "remote_url": "https://{ip}:{port}/".format(
                ip=get_default_host_ip(),
                port=serve_port,
            ),
            "port_forward": {"lifetime_sec": timeout_sec},
            # short lifetime of forward for fast reuse
        }

        if config_input:
            self.config.update(yaml.safe_load(config_input))

        if forward_config.enabled:
            self.config["port_forward"].update(forward_config)
            self.forward = command.local.Command(
                resource_name + "_forward",
                create="port_forward.py --yaml-from-stdin --yaml-to-stdout",
                stdin=self.config,
                opts=pulumi.ResourceOptions(parent=self),
            )
            self.config = yaml.safe_load(self.forward.stdout.yaml)
            self.config.update(
                {
                    "remote_url": "https://{ip}:{port}/".format(
                        ip=self.config["port_forward"]["public_ip"],
                        port=self.config["port_forward"]["public_port"],
                    ),
                }
            )
            self.result = self.forward.stdout
        else:
            self.result = yaml.safe_dump(self.config)

        self.register_outputs({})


class ServeOnce(pulumi.ComponentResource):
    """one time secure web data serve for eg. ignition data, or one time webhook with retrieved POST data"""

    def __init__(self, resource_name, config, opts=None):
        super().__init__("pkg:index:ServeOnce", resource_name, None, opts)

        self.executed = command.local.Command(
            resource_name,
            create="serve_once.py --yes",
            stdin=yaml.safe_dump(config),
            depends_on=config,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.result = self.executed.stdout
        self.register_outputs({})


class WriteRemoveable(pulumi.ComponentResource):
    """Writes image from given image_path to specified serial_numbered removable storage device"""

    def __init__(self, resource_name, image_path, serial_number, opts=None):
        super().__init__("pkg:index:WriteRemoveable", resource_name, None, opts)

        self.executed = command.local.Command(
            resource_name,
            create="write_removeable.py --yes {} {}".format(image_path, serial_number),
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.result = self.executed.returncode
        self.register_outputs({})


def serve_prepare(resource_name, config_input="", timeout_sec=45, opts=None):
    return ServePrepare(
        "serve_prepare_{}".format(resource_name),
        config_input=config_input,
        timeout_sec=timeout_sec,
        opts=opts,
    )


def serve_once(resource_name, payload, config, opts=None):
    this_config = copy.deepcopy(config)
    this_config.update({"payload": payload})
    return ServeOnce("serve_once_{}".format(resource_name), this_config, opts=opts)


def serve_simple(resource_name, yaml_str, opts=None):
    this_config = ServePrepare(
        "serve_prepare_{}".format(resource_name),
        config_input=yaml.safe_load(yaml_str),
    )
    return ServeOnce("serve_once_{}".format(resource_name), this_config, opts=opts)


def write_removeable(resource_name, image_path, serial_number, opts=None):
    return WriteRemoveable(
        "write_removeable_{}".format(resource_name),
        image_path=image_path,
        serial_number=serial_number,
        opts=opts,
    )


def main():
    import argparse
    import importlib
    import inspect

    # add base of project to begin of python import path list
    sys.path.insert(0, project_dir)

    parser = argparse.ArgumentParser(
        description="""
Equivalent to calling `pulumi up` on the selected library.function on the selected stack.
useful for oneshots like image building or transfer. calling example:
`pipenv run {this_dir_short}/tools.py sim {this_dir_short}.build build_openwrt`""".format(
            this_dir_short=os.path.basename(this_dir)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stack", type=str, help="Name of the stack", default="sim")
    parser.add_argument("library", type=str, help="Name of the library")
    parser.add_argument(
        "function",
        type=str,
        nargs="?",
        help="function name, will list all functions of library if empty",
    )
    parser.add_argument(
        "args",
        type=str,
        nargs="*",
        help="optional string args for function",
        default=[],
    )

    args = parser.parse_args()
    library = importlib.import_module(args.library)

    if not args.function:
        print("Available functions in library {}:".format(args.library))
        for name in dir(library):
            if callable(getattr(library, name)) and not name.startswith("__"):
                func = getattr(library, name)
                sig = inspect.signature(func)
                doc = "" if func.__doc__ is None else func.__doc__
                params = sig.parameters
                param_list = ", ".join(params.keys())
                print("{}({})  {}".format(name, param_list, doc))
        sys.exit()

    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "1"
    target_function = getattr(library, args.function)
    workspace = pulumi.automation.LocalWorkspace(work_dir=project_dir)
    stack = pulumi.automation.Stack.select(args.stack, workspace)

    stack.refresh(on_output=print)
    target_res = target_function(*args.args)
    stack.up(log_to_std_err=True, on_output=print)
    print(target_res)


if __name__ == "__main__":
    main()
