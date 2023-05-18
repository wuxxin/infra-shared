{# Homeassistant OS

- Buildroot linux, available for arm,x86-64

#}

{% importyaml "infra/defaults.yml" as defaults %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['pillar.get']('build', {})) %}

"""
haos_image = "{base}/{ver}/haos_{target}-{ver}.img.xz".format(
    base=haos_baseurl,
    ver=haos_version,
    target=haos_target,
)

"""