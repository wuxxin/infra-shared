#!/usr/bin/env python
"""
## Jinja and other Templating

### Python
- jinja_run
- jinja_run_template
- ToolsExtension(jinja2.ext.Extension)

- join_paths
- is_text
- load_text
- load_contents

- merge_dict_struct

- compile_selinux_module

"""

import base64
import copy
import glob
import os
import re
import stat
import subprocess

import chardet
import jinja2
import jinja2.ext


def join_paths(basedir, *filepaths):
    "combine filepaths with basedir like os.path.join, but remove leading '/' of each filepath"
    filepaths = [path[1:] if path.startswith("/") else path for path in filepaths]
    return os.path.join(basedir if basedir else "/", *filepaths)


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
        # self.environment.filters["list_files"] = self.list_files
        # self.environment.filters["list_dirs"] = self.list_dirs
        # self.environment.filters["has_executable_bit"] = self.has_executable_bit
        # self.environment.filters["get_filemode"] = self.get_filemode
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

    def regex_replace(
        self, value, pattern, replacement, ignorecase=False, multiline=False
    ):
        """replaces occurrences of the regular expression with another string"""
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        compiled_pattern = re.compile(pattern, flags)
        return compiled_pattern.sub(replacement, value)


def jinja_run(template_str, searchpath, environment={}):
    """renders a template string with environment, with optional includes from searchpath

    - searchpath can be string, or list of strings, file related filter only search searchpath

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

    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
    )
    template = env.get_template(template_filename)
    rendered = template.render(environment)
    return rendered


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
