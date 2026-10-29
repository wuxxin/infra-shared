{# OpenWRT OS

- linux distribution for embedded devices (router,switches,a.o.)
- available for x86, arm, mips, power

#}

{% set settings=salt['pillar.get']('openwrt') %}
{% set tmp_dir= grains["tmp_dir"] %}
{% set major= settings.target.partition("-")[0] %}
{% set minor= settings.target.partition("-")[2] %}
{% set baseurl= "{baseurl}/{ver}/targets/{major}/{minor}".format(
    baseurl=settings.baseurl,
    ver=settings.version, major=major, minor=minor) %}
{% set basename= "openwrt-imagebuilder-{ver}-{major}-{minor}.Linux-x86_64".format(
    ver=settings.version, major=major, minor=minor) %}

create_tmp_dir:
  file.directory:
    - name: {{ tmp_dir }}
    - makedirs: True

openwrt_signing_key:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt.sign.asc" }}
    - source: {{ settings.sign.baseurl ~ "/0x" ~ settings.sign.id ~ ".asc" }}
    - source_hash: {{ settings.sign.sha256sum }}

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
        set -eo pipefail
        if test -e {{ tmp_dir ~ "/gnupg" }}; then rm -r {{ tmp_dir ~ "/gnupg" }}; fi
        mkdir -p -m 700 {{ tmp_dir ~ "/gnupg" }}
        gpg --batch --no-tty --homedir {{ tmp_dir ~ "/gnupg" }} --import {{ tmp_dir ~ "/openwrt.sign.asc" }} > /dev/null 2>&1
        echo -e "5\ny\n" | gpg --batch --no-tty --homedir "{{ tmp_dir ~ "/gnupg" }}" --command-fd 0 --expert --edit-key "{{ settings.sign.subkey }}" trust > /dev/null 2>&1
        gpg --batch --no-tty --homedir {{ tmp_dir ~ "/gnupg" }} --verify {{ tmp_dir ~ "/openwrt.sha256sums.asc" }} {{ tmp_dir ~ "/openwrt.sha256sums" }}
        rm -r {{ tmp_dir ~ "/gnupg" }}

    - require:
      - file: openwrt_signing_key
      - file: imgbuilder_source_hashes
      - file: imgbuilder_hashes_signature

imgbuilder_source_archive:
  file.managed:
    - name: {{ tmp_dir ~ "/openwrt-imagebuilder.tar.zst" }}
    - source: {{ baseurl ~ "/" ~ basename ~ ".tar.zst" }}
    - source_hash: {{ tmp_dir ~ "/openwrt.sha256sums" }}
    - require:
      - cmd: verify_hashes_signature

imgbuilder_zstd_extracted:
  cmd.run:
    - cwd: {{ tmp_dir }}
    - name: zstd -d {{ tmp_dir ~ "/openwrt-imagebuilder.tar.zst" }} -o {{ tmp_dir ~ "/openwrt-imagebuilder.tar" }}
    - creates:
      - {{ tmp_dir ~ "/openwrt-imagebuilder.tar" }}
    - require:
      - file: imgbuilder_source_archive

imgbuilder_tar_extracted:
  cmd.run:
    - cwd: {{ tmp_dir }}
    - name: tar -xf {{ tmp_dir ~ "/openwrt-imagebuilder.tar" }} -C {{ tmp_dir }}
    - creates:
        - {{ tmp_dir ~ "/" ~ basename }}
    - require:
      - cmd: imgbuilder_zstd_extracted
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
          uci -q set network.lan.ipaddr='{{ settings.defaults.ip }}'
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
    - name: {{ 'umask 022 && mkdir -p tmp && make image PROFILE="{profile}" FILES="{files}" BIN_DIR="{bin_dir}" DISABLED_SERVICES="{disabled_services}" PACKAGES="{packages}"'.format(
        profile=settings.model,
        files= tmp_dir ~ "/openwrt-includes",
        bin_dir= tmp_dir ~ "/build",
        disabled_services=" ".join(settings.disabled_services),
        packages=" ".join(settings.packages)) }}
    - cwd: {{ tmp_dir ~ "/" ~ basename }}
    - creates: {{ tmp_dir ~ "/build/openwrt-{ver}-{major}-{minor}-{model}.manifest".format(
        ver=settings.version, major=major, minor=minor, model=settings.model) }}
    - output_loglevel: quiet
    - require:
      - cmd: imgbuilder_tar_extracted
      - file: include_uci_defaults
