import os
import json
import hashlib
import pulumi


def build_openwrt():
    from infra.authority import config, project_dir, ssh_factory
    from infra.tools import sha256sum_file, LocalSaltCall

    resource_name = "build_openwrt"
    pillar = {"build": config.get_object("build", {"openwrt": {}})}
    environment = {"authorized_keys": ssh_factory.authorized_keys.apply(lambda x: str(x))}
    resource = LocalSaltCall(
        resource_name,
        "state.sls",
        "infra.openwrt",
        pillar=pillar,
        environment=environment,
        triggers=[
            # trigger: build:openwrt:* , file:build:defaults.yml
            # changes to environment are triggered automatically
            hashlib.sha256(json.dumps(pillar["build"]["openwrt"]).encode("utf-8")).hexdigest(),
            sha256sum_file(os.path.join(project_dir, "infra", "defaults.yml")),
        ],
        opts=pulumi.ResourceOptions(depends_on=[ssh_factory]),
    )
    pulumi.export(resource_name, resource)
    return resource


def build_esphome():
    pass
