"""
## Pulumi - Build Embedded-OS Images, IOT Images, Image Addons
"""

import hashlib
import json
import os

from functools import reduce
from typing import Dict, Optional, List

import pulumi
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


def build_this(resource_name, sls_name, config_name, environment={}, opts=None):
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
    return build_this("build_raspberry_extras", "build_raspberry_extras", "raspberry")


def build_openwrt(resource_name, environment={}, opts=None):
    """build an openwrt image

    input environment:
    - authorized_keys: multiline string for authorized_keys content
    """
    return build_this(resource_name, "build_openwrt", "openwrt", environment, opts=opts)


def build_esphome(resource_name, environment={}, opts=None):
    """
    build yaml configured Sensor/Actor for ESP32 Devices on Arduino or ESP-IDF

    input environment:
    - build: json of custom build overwrites
    """
    return build_this(resource_name, "build_esphome", "esphome", environment, opts=opts)
