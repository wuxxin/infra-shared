import os
import yaml

from infra.tools import BuildFromSalt

this_dir = os.path.dirname(os.path.normpath(__file__))


def build_raspberry_extras():
    """Builds extra files for Raspberry Pi.

    This function triggers a SaltStack build to create extra files needed for
    Raspberry Pi devices, such as bootloader firmware.

    Returns:
        .result: A LocalSaltCall.result resource representing the Salt execution.
    """
    return BuildFromSalt(
        "build_raspberry_extras",
        sls_name="build_raspberry_extras",
        pillar=yaml.safe_load(open(os.path.join(this_dir, "build_defaults.yml"), "r")),
        environment={},
        sls_dir=this_dir,
    )
