#!/usr/bin/env python
"""
## Pulumi - Tools

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
- join_paths
- merge_dict_struct

### Components
- LocalSaltCall
- RemoteSaltCall

"""

import copy
import glob
import hashlib
import os
import re
import stat
import sys

import jinja2
import jinja2.ext
import pulumi
import pulumi_command as command
import yaml

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


def merge_dict_struct(struct1, struct2):
    "recursive merge of two dict like structs into one, struct2 takes precedence over struct1 if entry not None"

    def is_dict_like(v):
        return hasattr(v, "keys") and hasattr(v, "values") and hasattr(v, "items")

    def is_list_like(v):
        return hasattr(v, "append") and hasattr(v, "extend") and hasattr(v, "pop")

    merged = copy.deepcopy(struct1)
    if is_dict_like(struct1) and is_dict_like(struct2):
        for key in struct2:
            if key in struct1:
                # if the key is present in both dictionaries, recursively merge the values
                merged[key] = merge_dict_struct(struct1[key], struct2[key])
            else:
                merged[key] = struct2[key]
    elif is_list_like(struct1) and is_list_like(struct2):
        for item in struct2:
            if item not in struct1:
                merged.append(item)
    elif is_dict_like(struct1) and struct2 is None:
        # do nothing if first is dict, but second is None
        pass
    elif is_list_like(struct1) and struct2 is None:
        # do nothing if first is list, but second is None
        pass
    else:
        # the second input overwrites the first input
        merged = struct2
    return merged


class ToolsExtension(jinja2.ext.Extension):
    "jinja Extension with custom filter"

    def __init__(self, environment):
        super(ToolsExtension, self).__init__(environment)
        self.environment = environment
        self.environment.filters["list_files"] = self.list_files
        self.environment.filters["list_dirs"] = self.list_dirs
        self.environment.filters["has_executable_bit"] = self.has_executable_bit
        self.environment.filters["get_filemode"] = self.get_filemode
        self.environment.filters["regex_escape"] = self.regex_escape
        self.environment.filters["regex_search"] = self.regex_search
        self.environment.filters["regex_match"] = self.regex_match
        self.environment.filters["regex_replace"] = self.regex_replace

    def list_files(self, value):
        "returns available files in searchpath[0]/value as string, newline seperated"
        loader = self.environment.loader
        files = [
            os.path.relpath(os.path.normpath(entry), loader.searchpath[0])
            for entry in glob.glob(
                join_paths(loader.searchpath[0], value, "**"), recursive=True
            )
            if os.path.isfile(entry)
        ]
        return "\n".join(files)

    def list_dirs(self, value):
        "returns available directories in searchpath[0]/value as string, newline seperated"
        loader = self.environment.loader

        dirs = [
            os.path.relpath(os.path.normpath(entry), loader.searchpath[0])
            for entry in glob.glob(
                join_paths(loader.searchpath[0], value, "**"), recursive=True
            )
            if os.path.isdir(entry)
        ]
        return "\n".join(dirs)

    def has_executable_bit(self, value):
        "return boolean True if searchpath[0]/value file exists and has executable bit set, else False"
        loader = self.environment.loader
        f = join_paths(loader.searchpath[0], value)
        if not os.path.exists(f):
            return False
        mode = os.stat(f).st_mode
        if mode & stat.S_IXUSR:
            return True
        else:
            return False

    def get_filemode(self, value):
        "return octal filemode as string of file search using searchpath[0]/value or empty string"
        loader = self.environment.loader
        f = join_paths(loader.searchpath[0], value)
        if not os.path.exists(f):
            return ""
        return oct(stat.S_IMODE(os.stat(f).st_mode))

    def regex_escape(self, value):
        return re.escape(value)

    def regex_search(self, value, pattern, ignorecase=False, multiline=False):
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        obj = re.search(pattern, value, flags)
        if not obj:
            return
        return obj.groups()

    def regex_match(self, value, pattern, ignorecase=False, multiline=False):
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        obj = re.match(pattern, value, flags)
        if not obj:
            return
        return obj.groups()

    def regex_replace(self, value, pattern, replacement, ignorecase=False, multiline=False):
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        compiled_pattern = re.compile(pattern, flags)
        return compiled_pattern.sub(replacement, value)


def jinja_run(template_str, searchpath, environment={}):
    """renders a template string with environment, with optional includes from searchpath

    - searchpath can be string, or list of strings, file related filter only search searchpath[0]

    #### file related custom filter
    - "sub_dir/filename"|get_file_mode()
        - a string with the octal filemode of the file in searchpath[0]/filename, or "" if not found
    - "sub_dir/filename"|has_executable_bit()
        - a string with either "true" or "false" depending the executable bit, or "" if not found
    - "sub_dir"|list_files()
        - a string with a newline seperated list of files in searchpath/sub_dir
        - each of these listed files are available for "import x as y" in jinja
    - "sub_dir"|list_dirs()
        - a string with a newline seperated list of directories in searchpath/sub_dir

    #### regex related custom filter
    - "text"|regex_escape()
    - "text"|regex_search(pattern)
    - "text"|regex_match(pattern)
    - "text"|regex_replace(pattern, replacement)

    search,match,replace support additional args
    - ignorecase=True/*False
    - multiline=True/*False

    #### Example
    import files available under subdir "test" and translate into a saltstack state file

    ```jinja

    {% for f in 'test'|list_files().split('\\n') %}{% import f as c %}
    {{ f }}:
      file.managed:
        - contents: |
            {{ c|string()|indent(8) }}
    {% endfor %}
    ```

    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
    )
    template = env.from_string(template_str)
    rendered = template.render(environment)
    return rendered


def jinja_run_template(template_filename, searchpath, environment={}):
    """renders a template file available from searchpath with environment

    - searchpath can be a list of strings, template_filename can be from any searchpath
    - for details see `jinja_run`

    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
    )
    template = env.get_template(template_filename)
    rendered = template.render(environment)
    return rendered


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
                    private_key=self.props["sshkey"].private_key_openssh.apply(lambda x: x),
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
    parser.add_argument("stack", type=str, help="Name of the stack", default="sim")
    parser.add_argument("library", type=str, help="Name of the library")
    parser.add_argument("function", type=str, nargs="?", help="Name of the function")
    parser.add_argument(
        "args",
        type=str,
        nargs="*",
        help="optional args for function, only strings allowed",
        default=[],
    )
    args = parser.parse_args()

    library = importlib.import_module(args.library)

    if not args.function:
        print("Available functions in library {}:".format(args.library))
        function_list = [
            name
            for name in dir(library)
            if callable(getattr(library, name)) and not name.startswith("__")
        ]
        for function_name in function_list:
            function = getattr(library, function_name)
            signature = inspect.signature(function)
            parameters = signature.parameters
            parameter_list = ", ".join(parameters.keys())
            print("{}({})".format(function_name, parameter_list))
        sys.exit()

    target_function = getattr(library, args.function)
    project_name = os.path.basename(project_dir)
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "1"

    stack = pulumi.automation.select_stack(
        stack_name=args.stack,
        project_name=project_name,
        program=lambda: target_function(*args.args),
        work_dir=project_dir,
        opts=pulumi.automation.LocalWorkspaceOptions(work_dir=project_dir),
    )
    up_res = stack.up(log_to_std_err=True, on_output=print)
