"""
## Pulumi - Build Embedded-OS Images, IOT Images, Image Addons
"""

import hashlib
import json
import os

import pulumi
import yaml


this_dir = os.path.dirname(os.path.abspath(__file__))


def build_this(resource_name, sls_name, config_name, environment={}, opts=None):
    "build an image/os as running user with LocalSaltCall, trigger on config change, pass config as pillar, pass environment"

    from .tools import LocalSaltCall

    config = pulumi.Config("")
    def_pillar = {
        "build": yaml.safe_load(open(os.path.join(this_dir, "build_defaults.yml"), "r"))
    }
    pulumi_pillar = {"build": config.get_object("build", {config_name: {}})}
    if config_name not in def_pillar["build"]:
        def_pillar["build"].update({config_name: {}})
    if config_name not in pulumi_pillar["build"]:
        pulumi_pillar["build"].update({config_name: {}})
    def_pillar_hash = hashlib.sha256(
        json.dumps(def_pillar["build"][config_name]).encode("utf-8")
    ).hexdigest()
    pulumi_pillar_hash = hashlib.sha256(
        json.dumps(pulumi_pillar["build"][config_name]).encode("utf-8")
    ).hexdigest()

    resource = LocalSaltCall(
        resource_name,
        "state.sls",
        sls_name,
        pillar=pulumi_pillar,
        environment=environment,
        sls_dir=this_dir,
        triggers=[def_pillar_hash, pulumi_pillar_hash],
        opts=opts,
    )
    pulumi.export(resource_name, resource)
    return resource


def build_openwrt():
    "build an openwrt image"

    from .authority import ssh_factory

    environment = {"authorized_keys": ssh_factory.authorized_keys.apply(lambda x: str(x))}
    opts = pulumi.ResourceOptions(depends_on=[ssh_factory])
    return build_this("build_openwrt", "build_openwrt", "openwrt", environment, opts=opts)


def build_raspberry():
    "build raspberry 3/4 extra boot files"
    return build_this("build_raspberry", "build_raspberry", "raspberry")


def build_homeassistant():
    pass


def build_esphome():
    pass
