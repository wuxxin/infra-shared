import os
import json
import hashlib
import pulumi

# make fcos available for convinience
import infra.build.fcos as fcos


def build_openwrt():
    from infra.authority import config, project_dir, ssh_factory
    from infra.tools import sha256sum_file, LocalSaltCall

    # build openwrt image
    pillar = {"build": config.get_object("build", {"openwrt": {}})}
    environment = {"authorized_keys": ssh_factory.authorized_keys.apply(lambda x: str(x))}
    openwrt_image = LocalSaltCall(
        "build_openwrt_image",
        "state.sls",
        "build.openwrt",
        pillar=pillar,
        environment=environment,
        triggers=[
            # trigger: build:openwrt:* , file:build:defaults.yml
            # changes to environment are triggered automatically
            hashlib.sha256(json.dumps(pillar["build"]["openwrt"]).encode("utf-8")).hexdigest(),
            sha256sum_file(os.path.join(project_dir, "infra", "build", "defaults.yml")),
        ],
        opts=pulumi.ResourceOptions(depends_on=[ssh_factory]),
    )
    pulumi.export("build_openwrt_image", openwrt_image)
    return openwrt_image


def build_esphome():
    pass
