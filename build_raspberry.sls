{# Raspberry PI Extras for Fedora-CoreOS Boot

- available for rpi3 and rpi4

- outputs
  - raspberry/uboot
    - uboot bios boot files for rpi[34]
  - raspberry/uefi_rpi[34]
    - uefi bios boot files for rpi[34]
  - raspberry/eeprom_rpi4
    - eeprom update for rpi4

#}

{% import_yaml "build_defaults.yml" as defaults %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['pillar.get']('build', {})) %}


{% set tmp_dir= grains["tmp_dir"] %}
{% set download_dir= tmp_dir ~ "/download" %}

create_tmp_dir:
  file.directory:
    - name: {{ tmp_dir }}
    - makedirs: True

create_download_dir:
  file.directory:
    - name: {{ download_dir }}
    - makedirs: True


{# ### eeprom for rpi4 #}
{% set dest_dir = tmp_dir ~ "/eeprom_rpi4" %}

rpi_eeprom_rpi4_download:
  file.managed:
    - name: {{ download_dir ~ "/rpi-boot-eeprom-recovery-sd.zip"  }}
    - source: {{ settings.raspberry.eeprom_rpi4.fileurl.format(
        VERSION=settings.raspberry.eeprom_rpi4.version) }}
    - source_hash: {{ settings.raspberry.eeprom_rpi4.sha256sum }}
    - makedirs: True
    - require:
      - file: create_download_dir

rpi_eeprom_rpi4_dir:
  file.directory:
    - name: {{ dest_dir }}
    - makedirs: True

rpi_eeprom_rpi4_extracted:
  archive.extracted:
    - name: {{ dest_dir }}/build
    - source: {{ download_dir ~ "/rpi-boot-eeprom-recovery-sd.zip"  }}
    - source_hash: {{ settings.raspberry.eeprom_rpi4.sha256sum }}
    - extract_perms: False
    - enforce_toplevel: False
    - require:
      - file: rpi_eeprom_rpi4_download
      - file: rpi_eeprom_rpi4_dir


{# ### uboot bios for rpi3 and rpi4 #}
{% set dest_dir = tmp_dir ~ "/uboot" %}

rpi_fcos_uboot_download:
  file.managed:
    - name: {{ download_dir ~ "/uboot-images-armv8.rpm" }}
    - source: {{ settings.raspberry.uboot.fileurl.format(
        VERSION=settings.raspberry.uboot.version) }}
    - source_hash: {{ settings.raspberry.uboot.sha256sum }}
    - makedirs: True
    - require:
      - file: create_download_dir

rpi_fcos_uboot_extracted_dir:
  file.directory:
    - name: {{ download_dir ~ "/uboot_extracted" }}
    - makedirs: True

rpi_fcos_uboot_extracted:
  cmd.run:
    - name: |
        bsdtar -xf {{ download_dir ~ "/uboot-images-armv8.rpm" }} \
            -C {{ download_dir ~ "/uboot_extracted" }} \
            usr/share/uboot/rpi_3/u-boot.bin \
            usr/share/uboot/rpi_4/u-boot.bin
    - creates:
      - {{ download_dir ~ "/uboot_extracted" }}/usr/share/uboot/rpi_3/u-boot.bin
      - {{ download_dir ~ "/uboot_extracted" }}/usr/share/uboot/rpi_4/u-boot.bin
    - onchanges:
      - file: rpi_fcos_uboot_download
    - requires:
      - file: rpi_fcos_uboot_download
      - file: rpi_fcos_uboot_extracted_dir

rpi_fcos_uboot_dir:
  file.directory:
    - name: {{ dest_dir }}/boot/efi
    - makedirs: True

{% for r in ["3", "4"]%}
rpi_fcos_uboot_copy_rpi_{{ r }}:
  file.copy:
    - name: {{ dest_dir }}/boot/efi/rpi{{ r }}-u-boot.bin
    - source: {{ download_dir ~ "/uboot_extracted" }}/usr/share/uboot/rpi_{{ r }}/u-boot.bin
    - force: true
    - requires:
      - file: rpi_fcos_uboot_dir
      - file: rpi_fcos_uboot_extracted
{% endfor %}


{# ### uefi bios for rpi3 and rpi4 #}
{% for uefi_rpi in ["uefi_rpi3", "uefi_rpi4"] %}
  {% set dest_dir = tmp_dir ~ "/" ~ uefi_rpi %}

rpi_fcos_{{ uefi_rpi }}_dir:
  file.directory:
    - name: {{ dest_dir }}
    - makedirs: True

rpi_fcos_{{ uefi_rpi }}_download:
  file.managed:
    - name: {{ download_dir ~ "/" ~ uefi_rpi ~ "_firmware.zip" }}
    - source: {{ settings.raspberry[uefi_rpi].fileurl.format(
        VERSION=settings.raspberry[uefi_rpi].version) }}
    - source_hash: {{ settings.raspberry[uefi_rpi].sha256sum }}
    - makedirs: True
    - require:
      - file: rpi_fcos_{{ uefi_rpi }}_dir

rpi_fcos_uefi_{{ uefi_rpi }}_extracted:
  archive.extracted:
    - name: {{ dest_dir }}
    - source: {{ download_dir ~ "/" ~ uefi_rpi ~ "_firmware.zip" }}
    - source_hash: {{ settings.raspberry[uefi_rpi].sha256sum }}
    - extract_perms: False
    - enforce_toplevel: False
    - require:
      - file: rpi_fcos_{{ uefi_rpi }}_download

{% endfor %}

