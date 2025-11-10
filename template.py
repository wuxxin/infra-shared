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
import datetime
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
import fnmatch

from pathlib import Path
from typing import Optional, Union, List


def join_paths(basedir, *filepaths):
    """Joins file paths to a base directory, ensuring the result is within the base.

    This function combines one or more file paths with a base directory and
    resolves the absolute path. It raises a `ValueError` if the resulting path
    is outside the base directory, preventing directory traversal attacks.

    Args:
        basedir (str):
            The absolute base directory.
        *filepaths (str):
            The file paths to join to the base directory.

    Returns:
        str:
            The resolved, absolute path.

    Raises:
        ValueError:
            If the resolved path is outside the base directory.
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
    """Detects if a file is likely a text file.

    This function reads the beginning of a file and uses the `chardet` library
    to determine if it is a text file.

    Args:
        filepath (str):
            The path to the file.

    Returns:
        bool:
            True if the file is likely a text file, False otherwise.
    """
    with open(filepath, "rb") as file:
        data = file.read(8192)
    result = chardet.detect(data)
    return result["confidence"] > 0.5


def load_text(basedir, *filepaths):
    """Reads the content of a text file.

    Args:
        basedir (str):
            The base directory.
        *filepaths (str):
            The path to the file, relative to the base directory.

    Returns:
        str:
            The content of the file.
    """
    return open(join_paths(basedir, *filepaths), "r").read()


def load_contents(filepath):
    """Loads the contents of a file, either inline or as a data URL.

    This function checks if a file is a text file. If it is, the content is
    returned as a string. If it is a binary file, the content is returned as
    a base64-encoded data URL.

    Args:
        filepath (str):
            The path to the file.

    Returns:
        dict:
            A dictionary with either an "inline" key for text content or a
            "source" key for a data URL.
    """
    if is_text(filepath):
        contents = {"inline": open(filepath, "r").read()}
    else:
        contents = {
            "source": "data:;base64,"
            + base64.b64encode(open(filepath, "rb").read()).decode("utf-8")
        }
    return contents


def merge_dict_struct(struct1, struct2):
    """Recursively merges two data structures.

    This function merges two data structures, with values from the second
    structure taking precedence. It handles nested dictionaries and lists.

    Args:
        struct1 (any):
            The base data structure.
        struct2 (any):
            The data structure to merge into the base.

    Returns:
        any:
            The merged data structure.
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
    """A Jinja2 extension that provides custom filters and global functions."""

    def __init__(self, environment):
        """Initializes the ToolsExtension.

        Args:
            environment (jinja2.Environment):
                The Jinja2 environment.
        """
        super(ToolsExtension, self).__init__(environment)
        self.environment = environment
        self.environment.filters["regex_escape"] = self.regex_escape
        self.environment.filters["regex_search"] = self.regex_search
        self.environment.filters["regex_match"] = self.regex_match
        self.environment.filters["regex_replace"] = self.regex_replace
        self.environment.filters["toyaml"] = self.toyaml
        self.environment.filters["cidr2ip"] = self.cidr2ip
        self.environment.filters["cidr2reverse_ptr"] = self.cidr2reverse_ptr
        self.environment.filters["created_at"] = self.created_at
        self.environment.globals["local_now"] = self.local_now
        self.environment.globals["utc_now"] = self.utc_now

    def regex_escape(self, value: str) -> str:
        """Escapes special characters in a string for use in a regular expression.

        Args:
            value (str):
                The string to escape.

        Returns:
            str:
                The escaped string.
        """
        return re.escape(value)

    def regex_search(
        self, value: str, pattern: str, ignorecase=False, multiline=False
    ) -> tuple | None:
        """Searches a string for a match to a regular expression.

        Args:
            value (str):
                The string to search.
            pattern (str):
                The regular expression pattern.
            ignorecase (bool, optional):
                Whether to perform a case-insensitive search. Defaults to False.
            multiline (bool, optional):
                Whether to enable multi-line mode. Defaults to False.

        Returns:
            tuple | None:
                A tuple of the captured groups, or None if no match is found.
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

    def regex_match(
        self, value: str, pattern: str, ignorecase=False, multiline=False
    ) -> tuple | None:
        """Matches a regular expression at the beginning of a string.

        Args:
            value (str):
                The string to match.
            pattern (str):
                The regular expression pattern.
            ignorecase (bool, optional):
                Whether to perform a case-insensitive match. Defaults to False.
            multiline (bool, optional):
                Whether to enable multi-line mode. Defaults to False.

        Returns:
            tuple | None:
                A tuple of the captured groups, or None if no match is found.
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
        self, value: str, pattern: str, replacement: str, ignorecase=False, multiline=False
    ) -> str:
        """Replaces occurrences of a regular expression with a replacement string.

        Args:
            value (str):
                The string to search and replace.
            pattern (str):
                The regular expression pattern.
            replacement (str):
                The string to replace matches with.
            ignorecase (bool, optional):
                Whether to perform a case-insensitive search. Defaults to False.
            multiline (bool, optional):
                Whether to enable multi-line mode. Defaults to False.

        Returns:
            str:
                The modified string.
        """
        flags = 0
        if ignorecase:
            flags |= re.I
        if multiline:
            flags |= re.M
        compiled_pattern = re.compile(pattern, flags)
        return compiled_pattern.sub(replacement, value)

    def toyaml(self, value: object, inline=False) -> str:
        """Converts a Python object to a YAML string.

        Args:
            value (object):
                The Python object to serialize.
            inline (bool, optional):
                Whether to use an inline style for the YAML output. Defaults to False.

        Returns:
            str:
                The YAML representation of the object.
        """
        return yaml.safe_dump(value, default_flow_style=inline)

    def cidr2ip(self, value: str, index: int = 0) -> Optional[str]:
        """Converts a CIDR notation to an IP address.

        Args:
            value (str):
                The CIDR notation (e.g., "192.168.1.0/24").
            index (int, optional):
                The 0-based index of the usable IP address to return. Defaults to 0.

        Returns:
            str:
                The IP address at the specified index as a string.

        Raises:
            ValueError:
                If the CIDR is invalid, if index < 0, or if the index is out of range.
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
                raise ValueError(f"Index out of range: {index} of 1")

        if index < len(hosts):
            return str(hosts[index])
        else:
            raise ValueError(f"Index out of range: {index} of {len(hosts)}")

    def cidr2reverse_ptr(self, value: str) -> Optional[str]:
        """Converts a CIDR string to its reverse DNS zone name.

        Args:
            value (str):
                The network address in CIDR notation (e.g., "10.87.240.1/24"). Host bits
                in the address are ignored.

        Returns:
            str:
                The reverse DNS zone name (e.g., "240.87.10.in-addr.arpa.").

        Raises:
            ValueError:
                If the CIDR is invalid.
        """
        try:
            # strict=False allows for host bits to be set in the IP part (e.g., .1 in a /24).
            net = ipaddress.ip_network(value, strict=False)
            # The 'reverse_pointer' attribute automatically generates the correct in-addr.arpa or ip6.arpa name.
            return net.reverse_pointer
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {value} - {e}") from e

    def created_at(self, value: str) -> datetime.datetime | None:
        """Returns the modification time of a template file.

        Args:
            value (str):
                The relative path to the template file.

        Returns:
            datetime.datetime | None:
                The modification time of the file as a UTC datetime object, or None
                if the file cannot be found.
        """
        try:
            source, file_path, uptodate = self.environment.loader.get_source(
                self.environment, value
            )

            if file_path is None:
                return None

            epoch_time = os.path.getmtime(file_path)
            utc_dt = datetime.datetime.fromtimestamp(epoch_time, datetime.timezone.utc)
            # local_dt = utc_dt.astimezone()
            return utc_dt
        except Exception as e:
            return None

    def local_now(self) -> Optional[datetime.datetime]:
        """Returns the current time in the local timezone.

        Returns:
            datetime.datetime | None:
                A timezone-aware datetime object representing the current time.
        """
        return datetime.datetime.now(datetime.timezone.utc).astimezone()

    def utc_now(self) -> Optional[datetime.datetime]:
        """Returns the current time in the UTC timezone.

        Returns:
            datetime.datetime | None:
                A timezone-aware datetime object representing the current time in UTC.
        """
        return datetime.datetime.now(datetime.timezone.utc)


def jinja_run(
    template_str: str, searchpath: Union[str, List[str]], environment: dict = {}
) -> str:
    """Renders a Jinja2 template string.

    This function takes a Jinja2 template as a string, along with a search path
    for includes and an environment dictionary, and returns the rendered
    template.

    Args:
        template_str (str):
            The Jinja2 template string.
        searchpath (Union[str, List[str]]):
            A path or list of paths to search for included templates.
        environment (dict, optional):
            A dictionary of variables to make available in the template. Defaults to {}.

    Returns:
        str:
            The rendered template.
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
    """Renders a Jinja2 template file.

    This function loads a Jinja2 template from a file and renders it with the
    provided environment.

    - searchpath can be a list of strings, template_filename can be from any searchpath

    Args:
        template_filename (str):
            The name of the template file.
        searchpath (Union[str, List[str]]):
            A path or list of paths to search for the template file.
        environment (dict, optional):
            A dictionary of variables to make available in the template. Defaults to {}.

    Returns:
        str:
            The rendered template.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(searchpath), extensions=[ToolsExtension]
    )
    template = env.get_template(template_filename)
    rendered = template.render(environment)
    return rendered


def load_butane_dir(
    basedir: str | Path,
    environment: str,
    subdir: str | Path = "",
    exclude: list[str] = None,
    include: list[str] = None,
    search_root: str | Path | None = None,
):
    """Loads and processes Butane files from a directory.

    This function recursively finds all `.bu` files in a directory, renders
    them as Jinja2 templates, parses the resulting YAML, inlines any local
    file references, and merges the resulting dictionaries into a single
    dictionary.

    Args:
        basedir (str | Path):
            The base directory to search for Butane files.
        environment (str):
            The environment to use for template rendering.
        subdir (str | Path, optional):
            A subdirectory within the base directory to search. Defaults to "".
        exclude (list[str], optional):
            A list of file patterns to exclude. Supports fnmatch syntax. Defaults to None.
        include (list[str], optional):
            A list of specific files to include. If provided, only these files will be
            processed. Defaults to None.
        search_root (str | Path | None):
            The root directory that needs to be part of the final filename to be included.
            Defaults to None, if set, will check each included file for path starting with search_root

    Returns:
        dict:
            A dictionary containing the merged Butane configuration.
    """

    if exclude is None:
        exclude = []
    if include is None:
        include = []
    merged_dict = {}

    base_path = Path(basedir)
    files_to_process_relative: list[Path] = []
    search_subdir = Path(subdir)
    real_base_path = base_path.resolve()
    if not search_root:
        search_root = base_path
    else:
        search_root = Path(search_root)

    if include:
        files_to_process_relative = sorted([search_subdir / fname for fname in include])
    else:
        all_files_rel_to_base = []
        walk_root = base_path / search_subdir
        seen_real_paths = set()

        for root, dirs, files in os.walk(walk_root, followlinks=True):
            for file in files:
                if file.endswith(".bu"):
                    abs_file_path_found = Path(root) / file
                    try:
                        real_file = abs_file_path_found.resolve()
                        if real_file in seen_real_paths:
                            continue
                        if not real_file.is_relative_to(search_root):
                            print(
                                f"Warning: Skipping file {abs_file_path_found}. Resolved path {real_file} is outside base directory {base_path}"
                            )
                            continue

                        seen_real_paths.add(real_file)
                        rel_to_base = abs_file_path_found.relative_to(base_path)
                        all_files_rel_to_base.append(rel_to_base)

                    except (OSError, ValueError) as e:
                        print(
                            f"Warning: Skipping file {abs_file_path_found}. Could not resolve: {e}"
                        )
                        continue

        all_files_relative = sorted(all_files_rel_to_base)
        files_relative_to_subdir = []
        for p in all_files_relative:
            try:
                files_relative_to_subdir.append(p.relative_to(search_subdir))
            except ValueError as e:
                print(
                    f"Warning: p.relative_to(search_subdir) not found. p={p} search_subdir={search_subdir} exception={e}"
                )
                pass

        kept_files_relative_to_subdir = []
        if exclude:
            for f_path in files_relative_to_subdir:
                # Check if f_path (as string) matches ANY exclude pattern
                if not any(fnmatch.fnmatch(str(f_path), pattern) for pattern in exclude):
                    # If it matches no patterns, keep it
                    kept_files_relative_to_subdir.append(f_path)
        else:
            kept_files_relative_to_subdir = files_relative_to_subdir

        # convert the kept files back to paths relative to basedir
        files_to_process_relative = sorted(
            [search_subdir / f_path for f_path in kept_files_relative_to_subdir]
        )

    for fname_path in files_to_process_relative:
        fname = str(fname_path)
        source_dict = yaml.safe_load(jinja_run_file(fname, basedir, environment))
        inlined_dict = inline_local_files(source_dict, basedir)
        expanded_dict = expand_templates(inlined_dict, basedir, environment)
        merged_dict = merge_butane_dicts(merged_dict, expanded_dict)

    return merged_dict


def merge_butane_dicts(struct1, struct2):
    """Merges two Butane dictionaries with special handling for certain keys.

    This function merges two Butane configuration dictionaries. It has special
    logic to handle `storage` (files, links, directories) and `systemd`
    (units, drop-ins) sections to ensure that items are merged correctly,
    giving precedence to the second structure and de-duplicating based on
    path or name.

    Args:
        struct1 (dict):
            The base Butane dictionary.
        struct2 (dict):
            The Butane dictionary to merge into the base.

    Returns:
        dict:
            The merged Butane dictionary.
    """
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
    """Inlines local file references in a Butane dictionary.

    This function processes a Butane dictionary and replaces any local file
    references with the actual file content. It handles text files by inlining
    their content and binary files by base64-encoding them into data URLs.

    - for files and trees use source base64 encode if file type = binary, else use inline
    - storage:trees:[]:local -> files:[]:contents:inline/source
    - storage:files:[]:contents:local -> []:contents:inline/source
    - systemd:units:[]:contents_local -> []:contents
    - systemd:units:[]:dropins:[]:contents_local -> []:contents

    Args:
        yaml_dict (dict):
            The Butane dictionary.
        basedir (str):
            The base directory for resolving local file paths.

    Returns:
        dict:
            The Butane dictionary with local files inlined.
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
    """Processes templates within a Butane dictionary.

    This function expands templated content within a Butane dictionary. It
    supports Jinja2 templates and can compile SELinux TE files into modules.

    - storage:files[].contents.template
    - systemd:units[].template
    - systemd:units[].dropins[].template
    - template= "jinja": template the source through jinja
    - template= "selinux": compile selinux text configuration to binary (only storage.files)

    Args:
        yaml_dict (dict):
            The Butane dictionary.
        basedir (str):
            The base directory for resolving template paths.
        environment (dict):
            The environment to use for Jinja2 rendering.

    Returns:
        dict:
            The Butane dictionary with templates expanded.

    Raises:
        ValueError:
            If an unsupported template type is specified.
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
    """Translates a Butane dictionary to a SaltStack state dictionary.

    This function converts a Butane configuration dictionary into a format
    that can be used by SaltStack. It handles storage (directories, files,
    links) and systemd units. It can also generate status files that track
    service changes.

    - translation of:
        - storage:[directories,files,links]
        - sytemd:units[:dropins]
    - replace filename with /host_etc prefix if in /etc/hostname, /etc/hosts,
      or /etc/resolv.conf
    - if update_status=True:
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

    Args:
        yaml_dict (dict):
            The Butane dictionary to translate.
        update_status (bool, optional):
            Whether to generate service status files. Defaults to False.
        update_dir (str, optional):
            The directory to write status files to. Defaults to "/run/update-system-config".
        update_user (int, optional):
            The user ID for status files. Defaults to 0.
        update_group (int, optional):
            The group ID for status files. Defaults to 0.
        extra_pattern_list (list[str], optional):
            A list of extra file patterns to track for service changes. Defaults to [].

    Returns:
        dict:
            A SaltStack state dictionary.
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
    """Compiles an SELinux Type Enforcement (TE) file into a binary module.

    This function takes an SELinux TE file as a string, compiles it using
    `checkmodule`, and packages it into a binary module using
    `semodule_package`.

    Args:
        content (str):
            The content of the SELinux TE file.

    Returns:
        bytes:
            The compiled SELinux module as a binary string.

    Raises:
        Exception:
            If `checkmodule` or `semodule_package` fails.
    """
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
