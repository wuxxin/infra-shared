# Butane Translation

### Jinja Templating

in addition to jinja inside butane files,
files referenced from butane files with attribute `template=jinja`
will be rendered through jinja with the described Environment and optional includes from searchpath

#### Environment

- environment defaults available in jinja

```yaml
# include os/jinja_defaults.yml here
```

#### available custom regex filter

- `"text"|regex_escape()`
- `"text"|regex_search(pattern)`
- `"text"|regex_match(pattern)`
- `"text"|regex_replace(pattern, replacement)`

search,match,replace support additional args
- `ignorecase=True/*False`
- `multiline=True/*False`

### Butane Yaml

the butane configuration is created from

`ButaneTranspiler(butane_input, basedir, environment)`

| Name | source |  searchpath
|----|----|----|
| `base_dict`    | string butane_input | basedir
| `security_dict`| string *generated*  | basedir
| `system_dict`  | *.bu yaml | basedir+"/infra/os"
| `target_dict`  | *.bu yaml | targetdir

#### Merge Order
- `merged_dict  = system_dict+ target_dict+ security_dict+ base_dict`
    - **order** is earlier gets **overwritten by later**

#### for each "*.bu" in basedir+"infra/os", targetdir:

- `*.bu` recursive read and execute **jinja** with **environment** available
- parse result as yaml
- **inline** all local references
    - for files and trees use source with base64 encode if file type = binary

| source | dest |
|----|----|
| `storage:trees:[name]:local` | `files:[name]:contents:inline/source` |
| `storage:files:[name]:contents:local` | `[name]:contents:inline/source` |
| `systemd:units:[name]:contents_local` | `[name]:contents` |
| `systemd:units:[name]:dropins:[other]:contents_local` | `[other]:contents` |


- apply additional filter where **template** != ""
    - `storage:files:[name]:contents:template`
    - `systemd:units:[name]:template`
    - `systemd:units:[name]:dropins:[name]:template`

- merge together

### Ignition Json

the ignition spec file is created from the merged final butane yaml.

### Saltstack Yaml

The saltstack file is created from the resulting merged final butane yaml.
It meets all restrictions for the saltstack conversion.

Restrictions:

- only storage:directories/links/files and systemd:units[:dropins] are translated
- files must be inlined, files:contents must be of type inline or source (base64 encoded)
- systemd:units and systemd:units:dropins must be of type contents

Translation:

- [`/etc/hosts`, `/etc/hostname`, `/etc/resolv.conf`] are translated to `/host_etc/*`
- creates a commented, non uniqe, not sorted list of service base names
    - `update_dir=/run/user/1000/update-system-config`
    - `{upadate_dir}/service_changed.list` for services with changed configuration
    - `{upadate_dir}/service_enabled.list` for services to be enabled
    - `{upadate_dir}/service_disabled.list` for services to be disabled
    - see `update-system-config.service` for detailed usage of service_*
- `this_dir/update-system-config.sls` and `basedir/*.sls`are appended to output

Notes:
- `podman-systemd`, `compose.yml` and `nspawn` container:
    share the same namespace for service change recognition
    and should therefore not share the same name
- podman-systemd container config support files (beside .container and .volume),
    should also start with the servicename as part of the filename, to be recognized
