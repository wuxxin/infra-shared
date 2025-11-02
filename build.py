"""
## Pulumi - Build Embedded-OS Images, IOT Images, Image Addons

### Functions
- build_this_salt

- build_raspberry_extras
- build_openwrt
- build_esphome

### Components
- ESPhomeBuild

"""

import hashlib
import json
import os

from functools import reduce
from typing import Dict, Optional, List

import pulumi
import pulumi_command as command
import yaml


this_dir = os.path.dirname(os.path.abspath(__file__))


def get_nested_value(
    data: Dict, keys: List[str], default: Optional[bool] = None
) -> Optional[bool]:
    """
    Safely retrieves a nested value from a dictionary using reduce.
    Handles missing keys and ensures the final value is a boolean.
    """
    try:
        value = reduce(lambda d, k: d[k], keys, data)
        return value if isinstance(value, bool) else default
    except (KeyError, TypeError, AttributeError):
        # Handle missing keys or non-dict values
        return default


def build_this_salt(resource_name, sls_name, config_name, environment={}, opts=None):
    "build an image/os as running user with LocalSaltCall, trigger on config change, pass config as pillar, pass environment"

    from .tools import LocalSaltCall

    config = pulumi.Config("")
    # build_defaults and pulumi environment pillar are usually merged in salt-call, and not here
    def_pillar = {
        "build": yaml.safe_load(open(os.path.join(this_dir, "build_defaults.yml"), "r"))
    }
    pulumi_pillar = {"build": config.get_object("build") or {config_name: {}}}

    # do a manual merge for flag salt_debug
    defd = get_nested_value(def_pillar, ["build", "meta", "debug"])
    puld = get_nested_value(pulumi_pillar, ["build", "meta", "debug"])
    salt_debug = puld if puld is not None else (defd if defd is not None else False)

    # add default build config for config_name if not existing
    if config_name not in def_pillar["build"]:
        def_pillar["build"].update({config_name: {}})
    if config_name not in pulumi_pillar["build"]:
        pulumi_pillar["build"].update({config_name: {}})

    # calculate hashes from both pillars and environment
    def_pillar_hash = hashlib.sha256(
        json.dumps(def_pillar["build"][config_name]).encode("utf-8")
    ).hexdigest()
    pulumi_pillar_hash = hashlib.sha256(
        json.dumps(pulumi_pillar["build"][config_name]).encode("utf-8")
    ).hexdigest()
    environment_hash = hashlib.sha256(json.dumps(environment).encode("utf-8")).hexdigest()

    resource = LocalSaltCall(
        resource_name,
        "-l debug" if salt_debug else "",
        "state.sls",
        sls_name,
        pillar=pulumi_pillar,
        environment=environment,
        sls_dir=this_dir,
        triggers=[def_pillar_hash, pulumi_pillar_hash, environment_hash],
        opts=opts,
    )
    pulumi.export(resource_name, resource)
    return resource


def build_raspberry_extras():
    "build raspberry extra files"
    return build_this_salt("build_raspberry_extras", "build_raspberry_extras", "raspberry")


def build_openwrt(resource_name, environment={}, opts=None):
    """build an openwrt image

    input environment:
    - authorized_keys: multiline string for authorized_keys content
    """
    return build_this_salt(resource_name, "build_openwrt", "openwrt", environment, opts=opts)


class ESPhomeBuild(pulumi.ComponentResource):
    """
    Builds an ESPhome firmware image and uploads firmware to ESP32 for update

    Runs `esphome compile` to build firmware, `esphome upload` to upload firmware, cleans up temporary build files
    """

    def __init__(self, resourcename, config_yaml: str, environment, opts=None):
        """
        :param str resourcename: The logical name of the resource (e.g., 'intercom').
                                This name is used to determine paths and filenames
        :param str config_yaml: The full YAML configuration for the ESPhome device as a string
        :param dict environment: Environment variables to pass to the build command,
                                 used for substitutions in the ESPhome config (e.g., `!env_var`)
        :param pulumi.ResourceOptions opts: Optional Pulumi resource options
        """
        super().__init__("pkg:build:ESPhomeBuild", resourcename, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)

        stack = pulumi.get_stack()

        build_base = f"build/tmp/{stack}/.esphome"
        build_dir = f"{build_base}/build/{resourcename}"
        config_file = f"{build_base}/{resourcename}.yaml"

        # Create directories and pipe the config_yaml string into the config file
        self.write_config = command.local.Command(
            f"{resourcename}-write-config",
            create=f"mkdir -p {build_base} {build_dir} && cat > {config_file}",
            stdin=config_yaml,
            opts=child_opts,
        )

        self.build = command.local.Command(
            f"{resourcename}-build-image",
            create=f"ESPHOME_build_dir={build_dir} esphome compile {config_file}",
            environment=environment,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.write_config]),
        )

        self.upload = command.local.Command(
            f"{resourcename}-upload-image",
            create=f"ESPHOME_build_dir={build_dir} esphome upload {config_file}",
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.build]),
        )

        self.clean_build = command.local.Command(
            f"{resourcename}-clean-build",
            create=(
                f"rm -rf {config_file} {build_base}/idedata/{resourcename}.json {build_base}/storage/{resourcename}.yaml.json {build_dir}"
            ),
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.upload]),
        )

        self.register_outputs({})


def build_esphome(resource_name, config_yaml: str, environment={}, opts=None):
    """
    Builds andencrypts a firmware image for ESP32/ESP8266 devices using ESPhome

    input environment:
    - Any key/value pairs to be substituted into the ESPhome YAML
      (e.g., {'WIFI_SSID': 'my-network', 'WIFI_PASS': 'my-secret'})
    """
    return ESPhomeBuild(resource_name, config_yaml, environment=environment, opts=opts)
