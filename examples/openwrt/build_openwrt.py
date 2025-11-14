"""
## Pulumi - Build OpenWRT Embedded-OS Images

### Functions
- build_openwrt

"""

import os
import yaml

from infra.tools import BuildFromSalt

this_dir = os.path.dirname(os.path.normpath(__file__))


def build_openwrt(
    resource_name, environment={}, config_object_name="build_openwrt", opts=None
):
    """Builds an OpenWrt image.

    This function triggers a SaltStack build to create a customized OpenWrt firmware image.

    Args:
        resource_name (str):
            The name of the Pulumi resource.
        environment (dict, optional):
            A dictionary of environment variables to pass to the build. Defaults to {}.

            - authorized_keys: Multiline string for authorized_keys content baked into image

        config_object_name (str, optional):
            A name of a pulumi config object, that will be merged with the default openwrt pillar data.
            Defaults to "build_openwrt"
        opts (pulumi.ResourceOptions, optional):
            The options for the resource. Defaults to None.

    Returns:
        LocalSaltCall:
            A `LocalSaltCall` resource representing the Salt execution.
    """

    return BuildFromSalt(
        resource_name,
        sls_name="build_openwrt",
        pillar=yaml.safe_load(open(os.path.join(this_dir, "build_defaults.yml"), "r")),
        environment=environment,
        sls_dir=this_dir,
        pillar_key="openwrt",
        pulumi_key=config_object_name,
        opts=opts,
    )
