"""
## Tools 
 
### Functions

- ssh_copy
- ssh_deploy
- ssh_execute
- encrypted_local_export
- public_local_export

- sha256sum_file

### Components

- LocalSaltCall
- RemoteSaltCall

- SSHCopier
- SSHDeployer
- DataExport

"""

import hashlib
import os
import random
import yaml

import pulumi
import pulumi_command as command

this_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(this_dir, ".."))


def combine_path(prefix, path):
    "combine path like os.path.join, but remove first '/' on path if existing and prefix !=''"

    # os.path.join deletes any prefix path component if later component is an absolute path
    if prefix != "":
        return os.path.join(prefix, path[1:] if path[0] == "/" else path)
    else:
        return path


def sha256sum_file(filename):
    "sha256sum of file, logically backported from python 3.11"

    h = hashlib.sha256()
    buf = bytearray(2**18)
    view = memoryview(buf)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(view):
            h.update(view[:n])
    return h.hexdigest()


class SSHCopier(pulumi.ComponentResource):
    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHCopier", name, None, opts)

        self.props = props
        for key, value in self.props["files"].items():
            setattr(self, key, self.__transfer(name, key, value))
        self.register_outputs({})

    def __transfer(self, name, remote_path, local_path):
        resource_name = "copy_{}".format(remote_path.replace("/", "_"))
        file_hash = pulumi.Output.concat(sha256sum_file(local_path))
        full_remote_path = combine_path(self.props["remote_prefix"], remote_path)

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            copy_cmd = "cp {} {}"
            rm_cmd = "rm {} || true" if self.props["delete"] else ""

            file_transfered = command.local.Command(
                resource_name,
                create=copy_cmd.format(local_path, tmpfile),
                delete=rm_cmd.format(tmpfile),
                opts=pulumi.ResourceOptions(parent=self),
                triggers=[file_hash],
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
                    private_key=self.props["sshkey"].private_key_openssh.apply(lambda x: x),
                ),
                opts=pulumi.ResourceOptions(parent=self),
                triggers=[file_hash],
            )
        return file_transfered


class SSHDeployer(pulumi.ComponentResource):
    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHDeployer", name, None, opts)

        self.props = props
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
        full_remote_path = combine_path(self.props["remote_prefix"], remote_path)
        triggers = [0] if not self.props["refresh"] else [random.randrange(65536)]

        if self.props["simulate"]:
            os.makedirs(self.props["tmpdir"], exist_ok=True)
            tmpfile = os.path.abspath(os.path.join(self.props["tmpdir"], resource_name))
            value_deployed = command.local.Command(
                resource_name,
                create=cat_cmd.format(tmpfile),
                update=cat_cmd.format(tmpfile),
                delete=rm_cmd.format(tmpfile),
                stdin=data.apply(lambda x: str(x)),
                opts=pulumi.ResourceOptions(parent=self),
                triggers=triggers,
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
                opts=pulumi.ResourceOptions(parent=self),
                triggers=triggers,
            )
        return value_deployed


def ssh_copy(prefix, host, user, files={}, port=22, delete=False, remote_prefix="", opts=None):
    """copy a set of files from localhost to ssh target using ssh/sftp

    - files: {remotepath: localpath,}
    """

    from infra.authority import ssh_factory

    stack_name = pulumi.get_stack()
    props = {
        "host": host,
        "port": port,
        "user": user,
        "files": files,
        "sshkey": ssh_factory.provision_key,
        "delete": delete,
        "remote_prefix": remote_prefix,
        "simulate": stack_name.endswith("sim"),
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
    refresh=False,
    opts=None,
):
    """deploy a set of strings as small files to a ssh target

    - files: dict= {targetpath: targetdata,}
    """
    from infra.authority import ssh_factory

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
        "refresh": refresh,
        "simulate": stack_name.endswith("sim"),
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    deployed = SSHDeployer(prefix, props, opts=opts)
    # pulumi.export("{}_deploy".format(prefix), deployed)
    return deployed


def ssh_execute(prefix, host, user, cmdline, port=22, opts=None):
    """execute a command on a ssh target"""

    from infra.authority import ssh_factory

    resource_name = "{}_ssh_execute".format(prefix)
    stack_name = pulumi.get_stack()
    if stack_name.endswith("sim"):
        tmpdir = os.path.join(project_dir, "state", "tmp", stack_name)
        os.makedirs(tmpdir, exist_ok=True)
        ssh_executed = command.local.Command(
            resource_name,
            create="cat - > {}".format(os.path.join(tmpdir, resource_name)),
            delete="rm {} || true",
            stdin=cmdline,
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
            opts=opts,
        )
    return ssh_executed


class DataExport(pulumi.ComponentResource):
    "optional encrypt and store state data as local files under state/files/"

    def __init__(self, prefix, filename, data, key=None, filter="", delete=False, opts=None):
        super().__init__("pkg:index:DataExport", prefix, None, opts)

        stack_name = pulumi.get_stack()
        filter += " | " if filter else ""

        if key:
            self.filename = os.path.join(
                project_dir, "state", "files", stack_name, prefix, "{}.age".format(filename)
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

    from infra.authority import ssh_factory

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


def salt_config(resource_name, stack, base_dir, root_dir=None, tmp_dir=None, sls_dir=None):
    "generate a saltstack salt config, sls_dir defaults to base_dir/infra"

    config = yaml.safe_load(
        """
id: {id}
local: True
file_client: local
fileserver_backend:
- roots
log_level_logfile: info
root_dir: {root_dir}
conf_file: {root_dir}/minion
pki_dir: {root_dir}/etc/salt/pki/minion
pidfile: {root_dir}/var/run/salt-minion.pid
sock_dir: {root_dir}/var/run/salt/minion
cachedir: {root_dir}/var/cache/salt/minion
extension_modules: {root_dir}/var/cache/salt/minion/extmods
log_file: {root_dir}/var/log/salt/minion
file_roots:
  base:
  - {sls_dir}
pillar_roots:
  base:
  - {root_dir}/pillar
grains:
  base_dir: {base_dir}
  root_dir: {root_dir}
  tmp_dir: {tmp_dir}
  stack: {stack}
  resource_name: {resource_name}

""".format(
            id=os.path.basename(base_dir),
            base_dir=base_dir,
            stack=stack,
            resource_name=resource_name,
            root_dir=root_dir or os.path.join(base_dir, "state", "salt", stack, resource_name),
            tmp_dir=tmp_dir or os.path.join(base_dir, "state", "tmp", stack, resource_name),
            sls_dir=sls_dir if sls_dir else os.path.join(base_dir, "infra"),
        )
    )
    return config


class LocalSaltCall(pulumi.ComponentResource):
    """configure and execute a saltstack salt-call on a local provision machine"""

    def __init__(self, resource_name, *args, pillar={}, sls_dir=None, opts=None, **kwargs):
        super().__init__("pkg:index:LocalSaltCall", resource_name, None, opts)
        stack = pulumi.get_stack()
        config = salt_config(resource_name, stack, project_dir, sls_dir=sls_dir)
        pillar_dir = config["pillar_roots"]["base"][0]

        os.makedirs(config["root_dir"], exist_ok=True)
        os.makedirs(pillar_dir, exist_ok=True)

        with open(config["conf_file"], "w") as m:
            m.write(yaml.safe_dump(config))
        with open(os.path.join(pillar_dir, "top.sls"), "w") as m:
            m.write("base:\n  '*':\n    - main\n")
        with open(os.path.join(pillar_dir, "main.sls"), "w") as m:
            m.write(yaml.safe_dump(pillar))

        salt_executed = command.local.Command(
            resource_name,
            create="pipenv run salt-call -c {conf_dir} {args}".format(
                conf_dir=config["root_dir"],
                args=" ".join(args),
            ),
            opts=pulumi.ResourceOptions(parent=self),
            **kwargs,
        )
        return salt_executed


class RemoteSaltCall(pulumi.ComponentResource):
    "configure and execute a saltstack salt-call on a remote target machine"

    def __init__(
        self,
        resource_name,
        host,
        user,
        base_dir,
        *args,
        pillar={},
        salt="",
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
            resource_name, stack, base_dir, root_dir=root_dir, tmp_dir=tmp_dir, sls_dir=sls_dir
        )
        pillar_dir = self.config["pillar_roots"]["base"][0]
        sls_dir = self.config["file_roots"]["base"][0]
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
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.config_deployed]),
            **kwargs,
        )

        self.register_outputs({})


if __name__ == "__main__":
    """
    usage: $0 <stackname> <library-name> <function-name>

        calls a pulumi up on a selected function import.
        eg. $0 sim infra.build build_openwrt

    """
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "1"
    import target.gateway

    stack = pulumi.automation.select_stack(
        stack_name="sim",
        project_name="athome",
        program=target.gateway,
        work_dir=os.path.abspath(os.path.dirname(os.path.abspath(__file__))),
    )
    up_res = stack.up(on_output=print)
