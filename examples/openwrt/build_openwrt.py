"""
## Pulumi - Build OpenWRT Embedded-OS Images

### Functions
- build_openwrt

"""

import os

from infra.tools import BuildFromSalt

this_dir = os.path.dirname(os.path.normpath(__file__))


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
    return BuildFromSalt(resource_name, "build_openwrt", "openwrt", environment, opts=opts)
