{# ESP-Home Build

- environment 
- outputs

#}

{% set defaults=salt['pillar.get']('build') %}
{% set settings=salt['grains.filter_by']({'default': defaults},
    grain='default', default= 'default', merge= salt['environ.get']("build", "")| load_json) %}

{% set tmp_dir= grains["tmp_dir"] %}
{% set build_dir= tmp_dir ~ "/build_esphome" %}

create_tmp_dir:
  file.directory:
    - name: {{ tmp_dir }}
    - makedirs: True

create_download_dir:
  file.directory:
    - name: {{ download_dir }}
    - makedirs: True


in tmp/sim/build_esphome/ 
  .esphome
  device_name/

cd tmp/sim/build_esphome/ 
   set cached to this and subdir .esphome

in jinja: for envitem in environ that starts with BUILD_

in device_name/:  jinja templated device_name.yml

  # build_path: .esphome/build/intercom

age --encrypt -R $(ROOTDIR)authorized_keys -a > prod_passphrase.age


