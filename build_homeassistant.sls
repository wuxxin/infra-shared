{# Homeassistant OS

- home automation platform brokering MQTT,ZigBee,Bluetooth,Wifi and other automation network and protocols
- buildroot linux distribution
- available for x86, arm

#}

{% importyaml "build_defaults.yml" as defaults %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['pillar.get']('build', {})) %}

"""
haos_image = "{base}/{ver}/haos_{target}-{ver}.img.xz".format(
    base=haos_baseurl,
    ver=haos_version,
    target=haos_target,
)

"""