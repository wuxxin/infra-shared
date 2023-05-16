{# TrueNAS OS

- FreeBSD 13.x based Software NAS, available for x86-64

#}

{% importyaml "build/defaults.yml" as defaults %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['pillar.get']('build', {})) %}

"""

truenas_iso = "{base}/{ver}/STABLE/{patch}/x64/TrueNAS-{ver}-{patch}.iso".format(
    base=truenas_baseurl, ver=truenas_version, patch=truenas_patchlevel
)
truenas_sha256 = truenas_iso + ".sha256"
truenas_gpg = truenas_iso + ".gpg"
truenas_gpg_id = 0xC8D62DEF767C1DB0DFF4E6EC358EAA9112CF7946

"""