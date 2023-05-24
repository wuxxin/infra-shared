{# OpenWRT OS

- linux distribution for embedded devices (router,switches,a.o.)
- available for x86,arm,mips,power

#}

{% import_yaml "build_defaults.yml" as defaults %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['pillar.get']('build', {})) %}
{% set tmp_dir= grains["tmp_dir"] %}
{% set major= settings.openwrt.target.partition("-")[0] %}
{% set minor= settings.openwrt.target.partition("-")[2] %}
{% set baseurl= "{baseurl}/{ver}/targets/{major}/{minor}".format(
    baseurl=settings.openwrt.baseurl,
    ver=settings.openwrt.version, major=major, minor=minor) %}
{% set basename= "openwrt-imagebuilder-{ver}-{major}-{minor}.Linux-x86_64".format(
    ver=settings.openwrt.version, major=major, minor=minor) %}

create_tmp_dir:
  file.directory:
    - name: {{ tmp_dir }}
    - makedirs: True

openwrt_signing_key:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt.sign.asc" }}
    - source: {{ settings.openwrt.sign.baseurl ~ "/" ~ settings.openwrt.sign.id ~ ".asc" }}
    - source_hash: {{ settings.openwrt.sign.sha256sum }}

openwrt_signing_keyring:
  cmd.run:
    - name: |
        if test -e {{ tmp_dir ~ "/gnupg" }}; then rm -r {{ tmp_dir ~ "/gnupg" }}; fi &&
        mkdir -p -m 700 {{ tmp_dir ~ "/gnupg" }} &&
        gpg --homedir {{ tmp_dir ~ "/gnupg" }} --import {{ tmp_dir ~ "/openwrt.sign.asc" }} &&
        gpg --homedir {{ tmp_dir ~ "/gnupg" }} --export {{ settings.openwrt.sign.id }} > {{ tmp_dir ~ "/openwrt.sign.gpg" }} &&
        if test -e {{ tmp_dir ~ "/gnupg" }}; then rm -r {{ tmp_dir ~ "/gnupg" }}; fi
    - creates: {{ tmp_dir ~ "/openwrt.sign.gpg" }}
    - require:
      - file: openwrt_signing_key

imgbuilder_source_hashes:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt.sha256sums" }}
    - source: {{ baseurl ~ "/sha256sums" }}
    - skip_verify: true

imgbuilder_hashes_signature:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt.sha256sums.asc" }}
    - source: {{ baseurl ~ "/sha256sums.asc" }}
    - skip_verify: true

verify_hashes_signature:
  cmd.run:
    - name: |
        if test -e {{ tmp_dir ~ "/gnupg" }}; then rm -r {{ tmp_dir ~ "/gnupg" }}; fi &&
        mkdir -p -m 700 {{ tmp_dir ~ "/gnupg" }} &&
        gpgv --quiet --homedir {{ tmp_dir ~ "/gnupg" }} \
          --keyring {{ tmp_dir ~ "/openwrt.sign.gpg" }} \
          {{ tmp_dir ~ "/openwrt.sha256sums.asc" }} \
          {{ tmp_dir ~ "/openwrt.sha256sums" }}
    - require:
      - cmd: openwrt_signing_keyring
      - file: imgbuilder_source_hashes
      - file: imgbuilder_hashes_signature

imgbuilder_source_archive:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt-imagebuilder.tar.xz" }}
    - source: {{ baseurl ~ "/" ~ basename ~ ".tar.xz" }}
    - source_hash: {{ tmp_dir ~ "/openwrt.sha256sums" }}
    - require:
      - cmd: verify_hashes_signature

imgbuilder_source_extracted:
  archive.extracted:
    - name: {{ tmp_dir }}
    - source: {{ tmp_dir ~ "/openwrt-imagebuilder.tar.xz" }}
    - trim_output: 20
    - require:
      - file: imgbuilder_source_archive

prepare_openwrt_includes:
  file.directory:
    - name: {{ tmp_dir }}/openwrt-includes
    - makedirs: True

include_uci_defaults:
  file.managed:
    - name: {{ tmp_dir }}/openwrt-includes/etc/uci-defaults/99-custom
    - makedirs: True
    - contents: |
        if test "$(uci -q get network.lan.ipaddr)" = "192.168.1.1"; then
          uci -q set network.lan.ipaddr='{{ settings.openwrt.defaults.ip }}'
        fi
        if test ! -e /root/.ssh/authorized_keys; then
          mkdir -p -m 700 /root/.ssh/
          cat - > /root/.ssh/authorized_keys << EOF
        {%- for key in salt['environ.get']("authorized_keys").split("\n")|d("") %}
        {{ key }}
        {% endfor %}
        EOF
        fi
    - require:
      - file: prepare_openwrt_includes

build_openwrt_image:
  cmd.run:
    - name: {{ 'make image PROFILE="{profile}" FILES="{files}" BIN_DIR="{bin_dir}" DISABLED_SERVICES="{disabled_services}" PACKAGES="{packages}"'.format(
        profile=settings.openwrt.model,
        files= tmp_dir ~ "/openwrt-includes",
        bin_dir= tmp_dir ~ "/build",
        disabled_services=" ".join(settings.openwrt.disabled_services),
        packages=" ".join(settings.openwrt.packages)) }}
    - cwd: {{ tmp_dir ~ "/" ~ basename }}
    - creates: {{ tmp_dir ~ "/build/openwrt-{ver}-{major}-{minor}-{model}.manifest".format(
      ver=settings.openwrt.version, major=major, minor=minor, model=settings.openwrt.model) }}
    - output_loglevel: quiet
    - require:
      - archive: imgbuilder_source_extracted
      - file: include_uci_defaults
