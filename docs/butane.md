# Butane Translation

### Jinja Templating

in addition to jinja inside butane files,
files referenced from butane files with attribute template=jinja
will be rendered through jinja with the described Environment and optional includes from searchpath

#### Environment

- environment defaults available in jinja

```yaml
# see fcos/jinja_defaults.yml
```

- see [DNS-Resolver](dnsresolver.md) for DNS Resolver related optional variables examples


#### Custom regex filter

- "text"|regex_escape()
- "text"|regex_search(pattern)
- "text"|regex_match(pattern)
- "text"|regex_replace(pattern, replacement)

search,match,replace support additional args
- ignorecase=True/*False
- multiline=True/*False

### Butane Yaml

the butane configuration is created from

- base_dict    = jinja template butane_input, basedir=basedir
- security_dict= jinja template butane_security_keys, basedir=basedir
- fcos_dict    = jinja template *.bu yaml files from fcosdir
- target_dict  = jinja template *.bu yaml files from basedir

#### Merge Order
- merged_dict  = fcos_dict+ target_dict+ security_dict+ base_dict
    - order is earlier gets overwritten by later

#### for each *.bu in fcosdir, basedir:

- from basedir/*.bu recursive read and execute jinja with environment available
- parse result as yaml
- inline all local references
    - for files and trees use source with base64 encode if file type = binary
    - storage:trees:[]:local -> files:[]:contents:inline/source
    - storage:files:[]:contents:local -> []:contents:inline/source
    - systemd:units:[]:contents_local -> []:contents
    - systemd:units:[]:dropins:[]:contents_local -> []:contents
- apply additional filter where template != ""
    - storage:files[].contents.template
    - systemd:units[].template
    - systemd:units[].dropins[].template
- merge together with additional watching for contents:inline or source

### Ignition Json

the ignition spec file is created from the merged final butane yaml

### Saltstack Yaml

the saltstack spec file is created from a subset of the final butane yaml

- only storage:directories/links/files and systemd:units[:dropins] are translated
- files:contents must be of type inline or source (base64 encoded)
- systemd:units and systemd:units:dropins must be of type contents
- filenames /etc/hosts, /etc/hostname, /etc/resolv.conf are translated to /host_etc/*
- append this_dir/update-system-config.sls and basedir/*.sls to it
- additional outputs if {SALT_SERVICE_STATUS} == true:
    - creates a commented, non uniqe, not sorted list of service base names
        - {UPDATE_DIR}/`service_changed.list` for services with changed configuration
        - {UPDATE_DIR}/`service_enabled.list` for services to be enabled
        - {UPDATE_DIR}/`service_disabled.list` for services to be disabled
    - see `update-system-config.service` for detailed usage of service_*
- `podman-systemd`, `compose.yml` and `nspawn` container:
    share the same namespace for service change recognition
    and should therefore not share the same name
    - podman-systemd container config support files (beside .container and .volume),
    should also start with the servicename as part of the filename, to be recognized
