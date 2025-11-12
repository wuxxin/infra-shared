# Butane Translation

## Jinja Templating

in addition to jinja inside butane files,
files referenced with attribute `template=jinja` in

- storage:files[].contents.template
- systemd:units[].template
- systemd:units[].dropins[].template

will be rendered through jinja with the described Environment and optional includes from searchpath.

Documentation:

- [Jinja Template Documentation](https://jinja.palletsprojects.com/en/3.1.x/templates/)

### Environment

The Environment available in jinja for the butane translation.

- environment defaults available in jinja
- any default environment can be overwritten to liking
- HOSTNAME: the hostname argument will be set from the ButaneTranspiler
- some defaults (DNS_RESOLVER, LOCALE) can be set too on a project config (lowercase names)
    eg.:

```yaml
projectname:dns_resolver:
    upstream:
        - "10.10.10.1@53"
    upstream_tls: false
```

- os/jinja_defaults.yml:

```yaml
{% include "jinja_defaults.yml" %}
```

### available custom filter and functions

#### Regex

- `"text"|regex_escape()`
- `"text"|regex_search(pattern, ignorecase=False, multiline=False)`
- `"text"|regex_match(pattern, ignorecase=False, multiline=False)`
- `"text"|regex_replace(pattern, replacement, ignorecase=False, multiline=False)`

#### IPv4 Address Manipulation

- `"192.168.1.0/24"|cidr2ip(index=0)`
    - Converts a CIDR notation to an IP address.
    - Args:
        - cidr  (str): The CIDR notation (e.g., "192.168.1.0/24").
        - index (int, optional): The 0-based index of the usable IP address to return.
- `"10.87.240.1/24"|cidr2reverse_ptr()"`
    - Converts an IPv4 or IPv6 CIDR string into its corresponding reverse DNS zone name.
    - Args:
        - cidr_string: The network address in CIDR notation,
            e.g., "10.87.240.1/24". Host bits in the address are ignored
    - Returns:
        - str: The reverse DNS zone name as a string (e.g., "240.87.10.in-addr.arpa.")
    - Raises:
        - ValueError: If the CIDR is invalid

#### YAML Output

- `{"key": "value"}|toyaml(inline=False)`
    - dump dict structure to yaml string, same as jinja buildin `tojson` but outputs yaml instead of json
    - set inline=True for compact representation, default is multiline
#### Hashing

- `string|sha256sum`
    - calculates the SHA256 hash of a string and returns the hexadecimal representation

#### Time Now and File Time

- `"os/podman.bu"|created_at()`-> datetime.datetime | None
    - Return file modification datetime in UTC or None
    - Expects a relative path from the template search path
- `utc_now()`-> datetime.datetime
    - Return file modification datetime in UTC or None
- `local_now()`-> datetime.datetime
    - Return file modification datetime in local Timezone or None

in jinja, you can then call all python methods on the datetime.datetime objects available.

## Butane Yaml Creation

the butane configuration is created from

`ButaneTranspiler(butane_input, basedir, environment)`

| Name | source |  searchpath
|----|----|----
| `base_dict`    | butane_input:string | basedir
| `security_dict`| *generated*:string  | basedir
| `system_dict`  | `*.bu` yaml | basedir + `/infra/os`
| `target_dict`  | `*.bu` yaml | targetdir

### Merge Order

- `merged_dict  = system_dict+ target_dict+ security_dict+ base_dict`
    - **order** is earlier gets **overwritten by later**

### for each "*.bu" in basedir+"infra/os", targetdir

- `*.bu` recursive read and execute **jinja** with **environment** available
- parse result as yaml
- **inline** all local references
    - for files and trees use source with base64 encode if file type = binary

| source | dest
|----|----
| `storage:trees:[name]:local` | `files:[name]:contents:inline/source`
| `storage:files:[name]:contents:local` | `[name]:contents:inline/source`
| `systemd:units:[name]:contents_local` | `[name]:contents`
| `systemd:units:[name]:dropins:[other]:contents_local` | `[other]:contents`

- apply additional filter where **template** != ""
    - `storage:files:[name]:contents:template`
    - `systemd:units:[name]:template`
    - `systemd:units:[name]:dropins:[name]:template`

- merge together

## Ignition Json Creation

the ignition spec file is created from the merged final butane yaml.

## Saltstack Yaml Creation

The saltstack file is created from the resulting merged final butane yaml.
It meets all restrictions for the saltstack conversion.

- `this_dir/update-system-config.sls` and `basedir/*.sls`are appended to input

Restrictions:

- only storage:directories/links/files and systemd:units[:dropins] are translated
- files must be inlined, files:contents must be of type inline or source (base64 encoded)
- systemd:units and systemd:units:dropins must be of type contents

Translation:

- Files [`/etc/hosts`, `/etc/hostname`, `/etc/resolv.conf`] are translated to `/host_etc/*`

Changed Services:

- execution creates a commented, non uniqe, not sorted list of service base names
    - `update_dir=/run/user/1000/update-system-config`
    - `{update_dir}/service_changed.list` for services with changed configuration
    - `{update_dir}/service_enabled.list` for services to be enabled
    - `{update_dir}/service_disabled.list` for services to be disabled

see `update-system-config.service` for detailed usage of service_*

Notes:

- `podman-systemd`, `compose.yml` and `nspawn` container:
    share the same namespace for service change recognition
    and should therefore not share the same name
- podman-systemd container config support files (beside .container and .volume),
    should also start with the servicename as part of the filename, to be recognized
