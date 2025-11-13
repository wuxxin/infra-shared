"""
## Pulumi - Build ESPHome IOT-Images

### Functions
- build_esphome

### Components
- ESPhomeBuild

"""

import os

import pulumi
import pulumi_command as command


this_dir = os.path.dirname(os.path.normpath(__file__))


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
