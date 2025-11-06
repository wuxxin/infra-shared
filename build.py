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
    """Safely retrieves a nested boolean value from a dictionary.

    This function navigates through a nested dictionary using a list of keys
    and returns the value at the specified path. It handles cases where keys
    are missing or the path contains non-dictionary values.

    Args:
        data (Dict):
            The dictionary to search.
        keys (List[str]):
            A list of keys representing the path to the value.
        default (Optional[bool], optional):
            The default value to return if the key is not found or the value is not
            a boolean. Defaults to None.

    Returns:
        Optional[bool]:
            The retrieved boolean value, or the default value.
    """
    try:
        value = reduce(lambda d, k: d[k], keys, data)
        return value if isinstance(value, bool) else default
    except (KeyError, TypeError, AttributeError):
        # Handle missing keys or non-dict values
        return default


def build_this_salt(resource_name, sls_name, config_name, environment={}, opts=None):
    """Executes a local SaltStack state to build an image or OS.

    This function triggers a SaltStack execution to build a specified target,
    such as an OS image. It passes configuration from Pulumi and a defaults
    file as pillars to the Salt state. The build is triggered when the
    configuration or environment changes.

    Args:
        resource_name (str):
            The name of the Pulumi resource.
        sls_name (str):
            The name of the Salt state (SLS) file to execute.
        config_name (str):
            The name of the configuration section in the build defaults and Pulumi config.
        environment (dict, optional):
            A dictionary of environment variables to pass to the Salt call. Defaults to {}.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        LocalSaltCall:
            A `LocalSaltCall` resource representing the Salt execution.
    """

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
    """Builds extra files for Raspberry Pi.

    This function triggers a SaltStack build to create extra files needed for
    Raspberry Pi devices, such as bootloader firmware.

    Returns:
        LocalSaltCall:
            A `LocalSaltCall` resource representing the Salt execution.
    """
    return build_this_salt("build_raspberry_extras", "build_raspberry_extras", "raspberry")


def build_openwrt(resource_name, environment={}, opts=None):
    """Builds an OpenWrt image.

    This function triggers a SaltStack build to create a customized OpenWrt
    firmware image.

    Input environment:
        authorized_keys:
            Multiline string for authorized_keys content.

    Args:
        resource_name (str):
            The name of the Pulumi resource.
        environment (dict, optional):
            A dictionary of environment variables to pass to the build. Defaults to {}.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        LocalSaltCall:
            A `LocalSaltCall` resource representing the Salt execution.
    """
    return build_this_salt(resource_name, "build_openwrt", "openwrt", environment, opts=opts)


class ESPhomeBuild(pulumi.ComponentResource):
    """A Pulumi component for building and uploading ESPHome firmware.

    This component automates the process of building an ESPHome firmware image,
    uploading it to a device, and cleaning up the build artifacts.
    """

    def __init__(self, resourcename, config_yaml: str, environment, opts=None):
        """Initializes an ESPhomeBuild component.

        Args:
            resourcename (str):
                The name of the resource, used for file and directory names.
            config_yaml (str):
                The ESPHome configuration in YAML format.
            environment (dict):
                A dictionary of environment variables to pass to the build command.
            opts (pulumi.ResourceOptions, optional):
                The options for the resource. Defaults to None.
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
    """Builds and uploads an ESPHome firmware image.

    This function creates an `ESPhomeBuild` component to manage the build
    and upload process for an ESPHome device.

    Input environment:
        Any key/value pairs to be substituted into the ESPhome YAML
        (e.g., {'WIFI_SSID': 'my-network', 'WIFI_PASS': 'my-secret'})

    Args:
        resource_name (str):
            The name of the Pulumi resource.
        config_yaml (str):
            The ESPHome configuration in YAML format.
        environment (dict, optional):
            A dictionary of environment variables to pass to the build command. Defaults to {}.
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        ESPhomeBuild:
            An `ESPhomeBuild` component.
    """
    return ESPhomeBuild(resource_name, config_yaml, environment=environment, opts=opts)
