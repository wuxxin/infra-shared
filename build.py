import os
import json
import hashlib
import pulumi

from .authority import config, ssh_factory
from .tools import sha256sum_file, LocalSaltCall

this_dir = os.path.dirname(os.path.abspath(__file__))


def build_this(resource_name, sls_name, config_name):
    "build an image/os with LocalSaltCall, put config in pillar and authorized_keys in environment"
    pillar = {"build": config.get_object("build", {config_name: {}})}
    environment = {"authorized_keys": ssh_factory.authorized_keys.apply(lambda x: str(x))}
    resource = LocalSaltCall(
        resource_name,
        "state.sls",
        sls_name,
        pillar=pillar,
        environment=environment,
        sls_dir=this_dir,
        triggers=[
            # trigger on: pillar:build:config_name, file:build_defaults.yml
            # changes to environment are triggered automatically
            hashlib.sha256(
                json.dumps(pillar["build"][config_name]).encode("utf-8")
            ).hexdigest(),
            sha256sum_file(os.path.join(this_dir, "build_defaults.yml")),
        ],
        opts=pulumi.ResourceOptions(depends_on=[ssh_factory]),
    )
    pulumi.export(resource_name, resource)
    return resource


def build_openwrt():
    "build an openwrt image"
    return build_this("build_openwrt", "build_openwrt", "openwrt")


def build_homeassistant():
    "build an homeassistant image"
    return build_this("build_homeassistant", "build_homeassistant", "homeassistant")


def build_esphome():
    pass
