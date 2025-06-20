#!/usr/bin/env python
"""
## Jinja and Butane Templating

### Python
- jinja_run
- jinja_run_file
- load_butane_dir
- butane_to_salt

#### minor
- ToolsExtension(jinja2.ext.Extension)
- join_paths
- is_text
- load_text
- load_contents
- merge_butane_dicts
- merge_dict_struct
- inline_local_files
- expand_templates
- compile_selinux_module

"""

import base64
import copy
import glob
import os
import re
import stat
import subprocess
import ipaddress

import chardet
import jinja2
import jinja2.ext
import yaml

from typing import Optional, Union, List


def join_paths(basedir, *filepaths):
    """Combine filepaths with an absolute basedir, ensuring the resulting absolute path is within basedir

    - basedir (str): base directory starting with "/" to combine the filepaths with, defaults to "/" if empty
    - *filepaths (str): Variable number of file paths to be combined
    Returns: str: The combined path
    Raises: ValueError: If the resulting absolute path is outside the base directory
    """
    if not basedir:
        basedir = "/"
    # remove optional leading "/" of filepaths entries, because path.join cuts out parts before "/"
    filepaths = [path[1:] if path.startswith("/") else path for path in filepaths]
    # check if absolute path still startswith basedir, raise ValueError if not
    targetpath = os.path.join(basedir, *filepaths)
    abspath = os.path.abspath(targetpath)
    if not abspath.startswith(basedir):
        raise ValueError("Targetpath: {} outside Basedir: {}".format(abspath, basedir))
    return targetpath


def is_text(filepath):
    with open(filepath, "rb") as file:
        data = file.read(8192)
    result = chardet.detect(data)
    return result["confidence"] > 0.5


def load_text(basedir, *filepaths):
    return open(join_paths(basedir, *filepaths), "r").read()


def load_contents(filepath):
    if is_text(filepath):
        contents = {"inline": open(filepath, "r").read()}
    else:
        contents = {
            "source": "data:;base64,"
            + base64.b64encode(open(filepath, "rb").read()).decode("utf-8")
        }
    return contents


def merge_dict_struct(struct1, struct2):
    """recursive merge of two dict like structs into one
    struct2 takes precedence over struct1 if entry not None
    """

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
        # self.environment.filters["list_files"] = self.list_files
        # self.environment.filters["list_dirs"] = self.list_dirs
        # self.environment.filters["has_executable_bit"] = self.has_executable_bit
        # self.environment.filters["get_filemode"] = self.get_filemode
        self.environment.filters["regex_escape"] = self.regex_escape
        self.environment.filters["regex_search"] = self.regex_search
        self.environment.filters["regex_match"] = self.regex_match
        self.environment.filters["regex_replace"] = self.regex_replace
        self.environment.filters["yaml"] = self.yaml
        self.environment.filters["cidr2ip"] = self.cidr2ip

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
        "returns available directories in searchpath[0]/dir as string, newline seperated"
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
        "return boolean True if searchpath[0]/file exists and has executable bit set, else False"
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
        "return octal filemode as string of file in searchpath[0]/file or empty string"
        loader = self.environment.loader
        f = join_paths(loader.searchpath[0], value)
        if not os.path.exists(f):
            return ""
        return oct(stat.S_IMODE(os.stat(f).st_mode))

    def regex_escape(self, value):
        """escapes special characters in a string for use in a regular expression"""
        return re.escape(value)

    def regex_search(self, value, pattern, ignorecase=False, multiline=False):
        """searches the string for a match to the regular expression

        Returns: a tuple containing the groups captured in the match, or None
        """
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
        """tries to apply the regular expression at the start of the string

        Returns: a tuple containing the groups captured in the match, or None
        """
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
        """replaces occurrences of the regular expression with another string"""
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        compiled_pattern = re.compile(pattern, flags)
        return compiled_pattern.sub(replacement, value)

    def yaml(self, value, inline=False):
        """converts a python object to a YAML string
        inline: boolean indicating whether to use inline style for the YAML output
        """
        return yaml.safe_dump(value, default_flow_style=inline)

    def cidr2ip(self, value: str, index: int = 0) -> Optional[str]:
        """
        Converts a CIDR notation to an IP address.

        Args:
            value (str): The CIDR notation (e.g., "192.168.1.0/24")
            index (int, optional): The 0-based index of the usable IP address to return
        Returns:
            str | None: The IP address at the specified index as a string, or None if out of range
        Raises:
            ValueError: If the CIDR is invalid, or if index < 0
        """
        if index < 0:
            raise ValueError("index must be non-negative")
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {value} - {e}") from e

        hosts = list(network.hosts())
        if not hosts:  # Handle /32 and /31 (and /128 and /127 for IPv6)
            if index == 0:
                return str(network.network_address)
            else:
                return None

        if index < len(hosts):
            return str(hosts[index])
        else:
            return None


def jinja_run(
    template_str: str, searchpath: Union[str, List[str]], environment: dict = {}
) -> str:
    """
    Renders a Jinja2 template string with the given environment and search path.

    Args:
      template_str: The Jinja2 template string
      searchpath:   A string or list of strings of the file system paths to search for includes
      environment:  A dictionary representing the environment variables to pass to the template
    Returns:
      The rendered template as a string
    """
    try:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
        )
        template = env.from_string(template_str)
        return template.render(environment)
    except jinja2.exceptions.TemplateSyntaxError as e:
        error_line = e.lineno
        lines = template_str.splitlines()
        start = max(0, error_line - 6)  # 5 lines before + error line
        end = min(len(lines), error_line + 5)
        context = "\n".join(
            f"{i + 1}: {line}" for i, line in enumerate(lines[start:end], start)
        )
        new_message = (
            f"Jinja2 Template Syntax Error: {e}\n"
            f"Error occurred on line {error_line}.\n"
            f"Context:\n{context}"
        )
        e.context = context
        e.pulumi_message = new_message
        raise e


def jinja_run_file(template_filename, searchpath, environment={}):
    """renders a template file available from searchpath with environment

    - searchpath can be a list of strings, template_filename can be from any searchpath

    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
    )
    template = env.get_template(template_filename)
    rendered = template.render(environment)
    return rendered


def load_butane_dir(basedir, environment, subdir="", exclude=[], include=[]):
    "read basedir/**/*.bu files recursive, jinja template, parse yaml, inline files, merge, return dict"

    merged_dict = {}
    if include:
        files = sorted([os.path.join(subdir, fname) for fname in include])
    else:
        files = sorted(
            [
                fname
                for fname in glob.glob(
                    os.path.join(subdir, "**", "*.bu"), recursive=True, root_dir=basedir
                )
            ]
        )
        files = [f for f in files if f not in [os.path.join(subdir, ex) for ex in exclude]]

    for fname in files:
        source_dict = yaml.safe_load(jinja_run_file(fname, basedir, environment))
        inlined_dict = inline_local_files(source_dict, basedir)
        expanded_dict = expand_templates(inlined_dict, basedir, environment)
        merged_dict = merge_butane_dicts(merged_dict, expanded_dict)

    return merged_dict


def merge_butane_dicts(struct1, struct2):
    "butane overwrite aware storage:directories,files,links systemd:units:dropins dict merge"
    merged = merge_dict_struct(struct1, struct2)

    for section in ["files", "links", "directories"]:
        uniqitems = []
        seen = set()
        allitems = merged.get("storage", {}).get(section, [])

        if allitems:
            # get items of files, links, dirs in reverse order, take first, skip other
            for item in allitems[::-1]:
                if item["path"] not in seen:
                    seen.add(item["path"])
                    uniqitems.append(item)

            # reverse order, update dict
            merged["storage"][section] = uniqitems[::-1]

    uniqunits = {}
    seenunits = set()
    seendropins = set()
    allunits = merged.get("systemd", {}).get("units", [])

    if allunits:
        # get units in reverse order, take first, record dropins, skip other
        for unit in allunits[::-1]:
            if unit["name"] not in seenunits:
                seenunits.add(unit["name"])
                uniqunits.update({unit["name"]: unit})
                alldropins = unit.get("dropins", [])
                for dropin in alldropins:
                    unit_dropin = unit["name"] + "_" + dropin["name"]
                    if unit_dropin not in seendropins:
                        seendropins.add(unit_dropin)

        # get units in reverse order, get dropins, append if unknown, skip other
        for unit in allunits[::-1]:
            alldropins = unit.get("dropins", [])
            for dropin in alldropins:
                unit_dropin = unit["name"] + "_" + dropin["name"]
                if unit_dropin not in seendropins:
                    seendropins.add(unit_dropin)
                    uniqunits[unit["name"]]["dropins"].append(dropin)

        # convert units dict back to list, merge back
        merged["systemd"]["units"] = [v for k, v in uniqunits.items()]

    return merged


def inline_local_files(yaml_dict, basedir):
    """inline all local references

    - for files and trees use source base64 encode if file type = binary, else use inline
    - storage:trees:[]:local -> files:[]:contents:inline/source
    - storage:files:[]:contents:local -> []:contents:inline/source
    - systemd:units:[]:contents_local -> []:contents
    - systemd:units:[]:dropins:[]:contents_local -> []:contents
    """

    ydict = copy.deepcopy(yaml_dict)

    if "storage" in ydict and "trees" in ydict["storage"]:
        if "files" not in ydict["storage"]:
            ydict["storage"].update({"files": []})

        for tnr in range(len(ydict["storage"]["trees"])):
            t = ydict["storage"]["trees"][tnr]

            for lf in glob.glob(join_paths(basedir, t["local"], "**"), recursive=True):
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
                            "contents": load_contents(lf),
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
                    load_contents(join_paths(basedir, fname))
                )

    if "systemd" in ydict and "units" in ydict["systemd"]:
        for unr in range(len(ydict["systemd"]["units"])):
            u = ydict["systemd"]["units"][unr]

            if "contents_local" in u:
                fname = u["contents_local"]
                del ydict["systemd"]["units"][unr]["contents_local"]
                ydict["systemd"]["units"][unr].update({"contents": load_text(basedir, fname)})

            if "dropins" in u:
                for dnr in range(len(u["dropins"])):
                    d = ydict["systemd"]["units"][unr]["dropins"][dnr]

                    if "contents_local" in d:
                        fname = d["contents_local"]
                        del ydict["systemd"]["units"][unr]["dropins"][dnr]["contents_local"]
                        ydict["systemd"]["units"][unr]["dropins"][dnr].update(
                            {"contents": load_text(basedir, fname)}
                        )
    return ydict


def expand_templates(yaml_dict, basedir, environment):
    """template translation of contents from butane local references where template =! None

    - storage:files[].contents.template
    - systemd:units[].template
    - systemd:units[].dropins[].template
    - template= "jinja": template the source through jinja
    - template= "selinux": compile selinux text configuration to binary (only storage.files)
    """

    ydict = copy.deepcopy(yaml_dict)

    if "storage" in ydict and "files" in ydict["storage"]:
        for fnr in range(len(ydict["storage"]["files"])):
            f = ydict["storage"]["files"][fnr]

            if "contents" in f and "template" in f["contents"]:
                if f["contents"]["template"] not in ["jinja", "selinux-te2mod"]:
                    raise ValueError(
                        "Invalid option, template must be one of: jinja, selinux-te2mod"
                    )
                if "inline" not in f["contents"]:
                    raise ValueError(
                        "Invalid option, contents must be != None if template != None"
                    )

                if f["contents"]["template"] == "jinja":
                    data = jinja_run(f["contents"]["inline"], basedir, environment)
                    del ydict["storage"]["files"][fnr]["contents"]["template"]
                    ydict["storage"]["files"][fnr]["contents"].update({"inline": data})

                elif f["contents"]["template"] == "selinux-te2mod":
                    data = "data:;base64," + base64.b64encode(
                        compile_selinux_module(f["contents"]["inline"])
                    ).decode("utf-8")
                    del ydict["storage"]["files"][fnr]["contents"]["inline"]
                    del ydict["storage"]["files"][fnr]["contents"]["template"]
                    ydict["storage"]["files"][fnr]["contents"].update({"source": data})

    if "systemd" in ydict and "units" in ydict["systemd"]:
        for unr in range(len(ydict["systemd"]["units"])):
            u = ydict["systemd"]["units"][unr]
            if "template" in u and u["template"] not in ["jinja"]:
                raise ValueError("Invalid option, template must be one of: jinja")

            if "contents" in u and "template" in u:
                data = jinja_run(u["contents"], basedir, environment)
                ydict["systemd"]["units"][unr].update({"contents": data})
                del ydict["systemd"]["units"][unr]["template"]

            if "dropins" in u:
                for dnr in range(len(u["dropins"])):
                    d = ydict["systemd"]["units"][unr]["dropins"][dnr]
                    if "template" in d and d["template"] not in ["jinja"]:
                        raise ValueError("Invalid option, template must be one of: jinja")

                    if "contents" in d and "template" in d:
                        data = jinja_run(d["contents"], basedir, environment)
                        ydict["systemd"]["units"][unr]["dropins"][dnr].update(
                            {"contents": data}
                        )
                        del ydict["systemd"]["units"][unr]["dropins"][dnr]["template"]
    return ydict


def butane_to_salt(
    yaml_dict,
    update_status=False,
    update_dir="/run/update-system-config",
    update_user=0,
    update_group=0,
    extra_pattern_list=[],
):
    """translates a restricted butane dict into a saltstack dict

    - translation of
        - storage:[directories,files,links]
        - sytemd:units[:dropins]

    - replace filename with /host_etc prefix
        - if in /etc/hostname, /etc/hosts, /etc/resolv.conf

    - if update_service_status=True

        - write list of (enabled|disabled|masked) service names to
            - service_enabled.list
            - service_disabled.list
            - service_masked.list

        - write list of services with any file changed related to the service
            - to service_changed.list, if saltstack detects changes in
                - unit in /etc/systemd/system/name.*
                - dropin in /etc/systemd/system/name.d/*.conf
                - env in /etc/[local,containers,compose]/environment/name.env
                - file in /etc/containers/systemd/name*
                - file in /etc/[containers,compose]/build/name/*
                - the user supplied pattern list in extra_pattern_list
    """

    src = yaml_dict
    dest = {}
    service_list = {"enabled": [], "disabled": [], "masked": [], "changed": []}
    default_pattern_list = [
        r"/etc/systemd/system/([^/]+)\.[^\.]+",
        r"/etc/systemd/system/([^/]+)\.[^\.]+\.d/.+\.conf",
        r"/etc/local/environment/([^/.]+)\..*env",
        r"/etc/containers/environment/([^/.]+)\..*env",
        r"/etc/compose/environment/([^/.]+)\..*env",
        r"/etc/containers/systemd/([^/.]+)\..+",
        r"/etc/containers/build/([^/]+)/.+",
        r"/etc/compose/build/([^/]+)/.+",
    ]

    service_pattern_list = [
        re.compile("^" + pattern + "$")
        for pattern in [*default_pattern_list, *extra_pattern_list]
    ]

    def target_changed(target, target_type="file"):
        for pattern in service_pattern_list:
            if pattern.match(target):
                service_changed(pattern.sub("\\1", target), target, target_type)

    def service_changed(service, target, target_type):
        if service not in service_list["changed"]:
            service_list["changed"].append(
                {"service": service, "target": target, "target_type": target_type}
            )

    def service_status(service, action):
        if service not in service_list[action]:
            service_list[action].append(service)

    def tr_etc(path):
        if path in ["/etc/hostname", "/etc/hosts", "/etc/resolv.conf"]:
            return path.replace("/etc", "/host_etc")
        return path

    def ugm_append(dest, x):
        if "user" in x:
            if "id" in x["user"]:
                dest.append({"user": x["user"]["id"]})
            elif "name" in x["user"]:
                dest.append({"user": x["user"]["name"]})
        if "group" in x:
            if "id" in x["group"]:
                dest.append({"group": x["group"]["id"]})
            elif "name" in x["group"]:
                dest.append({"group": x["group"]["name"]})
        if "mode" in x:
            dest.append({"mode": "0" + oct(x["mode"])[2:]})

    if "storage" in src and "directories" in src["storage"]:
        for dnr in range(len(src["storage"]["directories"])):
            d = src["storage"]["directories"][dnr]
            dest.update({d["path"]: {"file": ["directory", {"makedirs": True}]}})
            ugm_append(dest[d["path"]]["file"], d)

    if "storage" in src and "links" in src["storage"]:
        for lnr in range(len(src["storage"]["links"])):
            li = src["storage"]["links"][lnr]
            dest.update({li["path"]: {"file": ["symlink"]}})
            dest[li["path"]]["file"] += [{"makedirs": True}, {"target": li["target"]}]
            if "hard" in li and li["hard"]:
                dest[li["path"]]["file"].append({"hard": True})
            ugm_append(dest[li["path"]]["file"], li)
            target_changed(li["path"])

    if "storage" in src and "files" in src["storage"]:
        for fnr in range(len(src["storage"]["files"])):
            f = src["storage"]["files"][fnr]
            fname = tr_etc(f["path"])
            ftype = "file"
            dest.update({fname: {"file": ["managed", {"makedirs": True}]}})
            ugm_append(dest[fname]["file"], f)
            if "contents" not in f:
                continue

            if "inline" in f["contents"]:
                dest[fname]["file"].append({"contents": f["contents"]["inline"]})

            elif "source" in f["contents"]:
                if f["contents"]["source"].startswith("data:"):
                    dest[fname].update({"cmd": ["run"]})
                    create_cmd = 'cat <<"EOF" | base64 -d > ' + fname + "\n"
                    dest[fname]["cmd"] += [
                        {"name": create_cmd + f["contents"]["source"] + "\nEOF\n"},
                        {"unless": "base64 -d < " + fname + "| cmp -s " + fname + " -"},
                        {"creates": fname},
                    ]
                    ftype = "cmd"
                else:
                    dest[fname]["file"].append({"source": f["contents"]["source"]})

            if "verification" in f["contents"]:
                dest[fname]["file"].append({"source_hash": f["contents"]["verification"][7:0]})

            target_changed(fname, ftype)

    if "systemd" in src and "units" in src["systemd"]:
        for unr in range(len(src["systemd"]["units"])):
            u = src["systemd"]["units"][unr]
            ufname = "/etc/systemd/system/" + u["name"]

            if "enabled" in u:
                service_status(u["name"], "enabled" if u["enabled"] else "disabled")
            if "mask" not in u or not u["mask"]:
                if "contents" in u:
                    dest.update({ufname: {"file": ["managed"]}})
                    dest[ufname]["file"] += [
                        {"follow_symlinks": "false"},
                        {"contents": u["contents"]},
                    ]
                    target_changed(ufname)
            else:
                dest.update({ufname: {"file": ["symlink"]}})
                dest[ufname]["file"] += [{"target": "/dev/null"}, {"force": True}]
                service_status(u["name"], "masked")
                target_changed(ufname)

            if "dropins" in u:
                for udnr in range(len(u["dropins"])):
                    ud = u["dropins"][udnr]
                    udfname = "/etc/systemd/system/" + u["name"] + ".d/" + ud["name"]
                    dest.update({udfname: {"file": ["managed"]}})
                    dest[udfname]["file"] += [
                        {"makedirs": True},
                        {"contents": ud["contents"]},
                    ]
                    target_changed(udfname)

    if update_status:
        for status in ["enabled", "disabled", "masked", "changed"]:
            # create empty files
            shortname = "create_service_" + status
            sfname = os.path.join(update_dir, "service_" + status + ".list")
            dest.update({shortname: {"file": ["managed"]}})
            dest[shortname]["file"] += [
                {"name": sfname},
                {"user": update_user},
                {"group": update_group},
            ]

            # write enabled, disabled and masked to *.list
            if status != "changed":
                dest[shortname]["file"] += [
                    {"contents": "\n".join([name for name in service_list[status]])}
                ]

        # prepare service_changed.list accumulator
        dest.update({"service_changed": {"file": ["blockreplace"]}})
        dest["service_changed"]["file"] += [
            {"name": os.path.join(update_dir, "service_changed.list")},
            {"marker_start": "# START"},
            {"marker_end": "# END"},
            {"content": ""},
            {"append_if_not_found": True},
            {"show_changes": True},
            {"require": [{"file": "create_service_changed"}]},
        ]

        # write all service related found change accumulators
        # let saltstack figure out which is changed using "onchanges"
        for entry in service_list["changed"]:
            cname = "service_changed_" + entry["target"]
            dest.update({cname: {"file": ["accumulated"]}})
            dest[cname]["file"] += [
                {"filename": os.path.join(update_dir, "service_changed.list")},
                {"text": entry["service"]},
                {"onchanges": [{entry["target_type"]: entry["target"]}]},
                {"require_in": [{"file": "service_changed"}]},
            ]

    return dest


def compile_selinux_module(content):
    """compile_selinux_module Fixme: think how to change from text stdin to binary stdout"""

    timeout_seconds = 10
    chk_process = subprocess.Popen(
        ["checkmodule", "-M", "-m", "-o", "/dev/stdout", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    chk_output, chk_error = chk_process.communicate(input=content, timeout=timeout_seconds)
    if chk_process.returncode != 0:
        raise Exception("checkmodule failed:\n{}".format(chk_error))
    pkg_process = subprocess.Popen(
        ["semodule_package", "-o", "/dev/stdout", "-m", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    pkg_output, pkg_error = pkg_process.communicate(input=chk_output, timeout=timeout_seconds)
    if pkg_process.returncode != 0:
        raise Exception("semodule_package failed:\n{}".format(pkg_error))

    return pkg_output
