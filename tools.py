#!/usr/bin/env python
"""
## Tools 

- Usage as command line utility: `pipenv $0 stack library function`

### Functions
- ssh_copy
- ssh_deploy
- ssh_execute

- encrypted_local_export
- public_local_export

- jinja_run
- jinja_run_template

- log_warn
- sha256sum_file

### Components
- LocalSaltCall
- RemoteSaltCall

"""

import os
import sys
import stat
import hashlib
import random
import glob

import yaml
import jinja2

import jinja2.ext
import pulumi
import pulumi_command as command

this_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(this_dir, ".."))


def log_warn(x):
    "write str(var) to pulumi.log.warn with line numbering, to be used as var.apply(log_warn)"
    pulumi.log.warn(
        "\n".join(["{}:{}".format(n + 1, l) for n, l in enumerate(str(x).splitlines())])
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


class BasePathFileLoader(jinja2.FileSystemLoader):
    def __init__(self, basepath):
        self.basepath = os.path.normpath(basepath)
        super().__init__(self.basepath)


class FilesExtension(jinja2.ext.Extension):
    """jinja Extension for list_files, has_executable_bit and get_filemode filter"""

    def __init__(self, environment):
        super(FilesExtension, self).__init__(environment)
        self.environment = environment
        self.environment.filters["list_files"] = self.list_files
        self.environment.filters["has_executable_bit"] = self.has_executable_bit
        self.environment.filters["get_filemode"] = self.get_filemode

    def list_files(self, value):
        "returns available files in basepath/value as string, newline seperated"
        loader = self.environment.loader
        globpath = join_paths(loader.basepath, value, "**")
        files = [
            os.path.relpath(os.path.normpath(file), loader.basepath)
            for file in glob.glob(globpath, recursive=True)
            if os.path.isfile(file)
        ]
        return "\n".join(files)

    def has_executable_bit(self, value):
        "return 'True' or 'False' depending if basepath/value file has executable bit set or empty string"
        loader = self.environment.loader
        f = join_paths(loader.basepath, value)
        if not os.path.exists(f):
            return ""
        mode = os.stat(f).st_mode
        if mode & stat.S_IXUSR:
            return "True"
        else:
            return "False"

    def get_filemode(self, value):
        "return octal filemode as string of file search using basepath/value or empty string"
        loader = self.environment.loader
        f = join_paths(loader.basepath, value)
        if not os.path.exists(f):
            return ""
        return oct(stat.S_IMODE(os.stat(f).st_mode))


def jinja_run(template_str, base_dir, environment={}):
    """renders a template string with environment, with optional includes from base_dir

    custom filter available:

    - "sub_dir/filename"|get_file_mode() returns
        - a string with the octal filemode of the file in base_dir/filename, or "" if not found

    - "sub_dir/filename"|has_executable_bit() returns
        - a string with either "True" or "False" depending the executable bit, or "" if not found

    - "sub_dir"|list_files() returns
        - a string with a newline seperated list of files in base_dir/sub_dir
        - each of these listed files are available for "import x as y" in jinja

    Example:
        - import files available under subdir "test" and translate into a saltstack state file

    ```jinja

    {% for f in 'test'|list_files().split('\n') %}{% import f as c %}
    {{ f }}:
      file.managed:
        - contents: |
            {{ c|string()|indent(8) }}
    {% endfor %}
    ```

    """
    env = jinja2.Environment(loader=BasePathFileLoader(base_dir), extensions=[FilesExtension])
    template = env.from_string(template_str)
    rendered = template.render(environment)
    return rendered


def jinja_run_template(template_filename, base_dir, environment={}):
    """renders a template file available from base_dir with environment

    - for details see `jinja_run`

    """
    env = jinja2.Environment(loader=BasePathFileLoader(base_dir), extensions=[FilesExtension])
    template = env.get_template(template_filename)
    rendered = template.render(environment)
    return rendered


class SSHCopier(pulumi.ComponentResource):
    """Pulumi Component: use with function ssh_copy()"""

    def __init__(self, name, props, opts=None):
        super().__init__("pkg:index:SSHCopier", name, None, opts)

        self.props = props
        for key, value in self.props["files"].items():
            setattr(self, key, self.__transfer(name, key, value))
        self.register_outputs({})

    def __transfer(self, name, remote_path, local_path):
        resource_name = "copy_{}".format(remote_path.replace("/", "_"))
        file_hash = pulumi.Output.concat(sha256sum_file(local_path))
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)

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
    """Pulumi Component: use with function ssh_deploy()"""

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
        full_remote_path = join_paths(self.props["remote_prefix"], remote_path)
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

    - files: {remotepath: localpath,}
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
    refresh=False,
    simulate=None,
    opts=None,
):
    """deploy a set of strings as small files to a ssh target

    if simulate==True: data is not transfered but written out to state/tmp/stack_name
    if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    - files: dict= {targetpath: targetdata,}
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
        "refresh": refresh,
        "simulate": stack_name.endswith("sim") if simulate is None else simulate,
        "tmpdir": os.path.join(project_dir, "state", "tmp", stack_name),
    }
    deployed = SSHDeployer(prefix, props, opts=opts)
    # pulumi.export("{}_deploy".format(prefix), deployed)
    return deployed


def ssh_execute(prefix, host, user, cmdline, port=22, simulate=None, opts=None):
    """execute a command as user on a ssh target host

    if simulate==True: command is not executed but written out to state/tmp/stack_name
    if simulate==None: simulate=pulumi.get_stack().endswith("sim")

    """

    from .authority import ssh_factory

    resource_name = "{}_ssh_execute".format(prefix)
    stack_name = pulumi.get_stack()
    simulate = stack_name.endswith("sim") if simulate is None else simulate

    if simulate:
        tmpdir = os.path.join(project_dir, "state", "tmp", stack_name)
        os.makedirs(tmpdir, exist_ok=True)
        ssh_executed = command.local.Command(
            resource_name,
            create="cat - > {}".format(os.path.join(tmpdir, resource_name)),
            delete="rm {} || true".format(os.path.join(tmpdir, resource_name)),
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
    """store state data (with optional encryption) as local files under state/files/

    use with
        - public_local_export()
        - encrypted_local_export()
    """

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

    root_dir = root_dir or os.path.join(base_dir, "state", "salt", stack_name, resource_name)
    tmp_dir = tmp_dir or os.path.join(base_dir, "state", "tmp", stack_name, resource_name)
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

    Example: build openwrt image
        LocalSaltCall("build_openwrt", "state.sls", "build_openwrt",
            pillar={}, environment={}, sls_dir=this_dir)

    """

    def __init__(self, resource_name, *args, pillar={}, sls_dir=None, opts=None, **kwargs):
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


if __name__ == "__main__":
    import argparse
    import importlib

    # add base of project to begin of python import path list
    sys.path.insert(0, project_dir)

    parser = argparse.ArgumentParser(
        description="""
Equivalent to `pulumi up` on the selected library.function import on the selected stack.
eg. `pipenv run {this_dir_short}/tools.py sim {this_dir_short}.build build_openwrt`""".format(
            this_dir_short=os.path.basename(this_dir)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("stack", type=str, help="Name of the stack", default="sim")
    parser.add_argument("library", type=str, help="Name of the library")
    parser.add_argument("function", type=str, help="Name of the function")
    args = parser.parse_args()

    target_library = importlib.import_module(args.library)
    target_function = getattr(target_library, args.function)
    project_name = os.path.basename(project_dir)
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "1"

    stack = pulumi.automation.select_stack(
        stack_name=args.stack,
        project_name=project_name,
        program=target_function,
        work_dir=project_dir,
        opts=pulumi.automation.LocalWorkspaceOptions(work_dir=project_dir),
    )
    up_res = stack.up(log_to_std_err=True, on_output=print)
