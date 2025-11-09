import os
import yaml
import json
from pulumi.automation import Stack
from .utils import add_pulumi_program


def test_butane_verification_hash(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    program = """
import pulumi
from infra.os import ButaneTranspiler, RemoteDownloadIgnitionConfig
from infra.tools import ServePrepare
from infra.authority import create_host_cert

# Minimal host certificate
tls = create_host_cert("test-host", "test-host", ["test-host"])

# Minimal Butane config
butane_yaml = pulumi.Output.from_input(
    '''
variant: fcos
version: 1.6.0
'''
)

# Transpile Butane to get ignition config and hash
host_config = ButaneTranspiler(
    "test-butane",
    "test-host",
    tls,
    butane_yaml,
    ".",
    {},
)

# Prepare to serve the ignition config
serve_config = ServePrepare(
    "test-serve",
    serve_interface="lo",
    request_header={
        "Verification-Hash": host_config.ignition_config_hash,
    },
)

# Create a remote download ignition config
public_config = RemoteDownloadIgnitionConfig(
    "test-remote-dl",
    "test-host",
    remote_url=serve_config.config.apply(lambda x: x["remote_url"]),
    remote_hash=host_config.ignition_config_hash,
)

pulumi.export("host_config", host_config)
pulumi.export("serve_config", serve_config.config)
pulumi.export("public_config_stdout", public_config.ignition_config.stdout)
pulumi.export("ignition_hash", host_config.ignition_config_hash)

"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    serve_config = up_result.outputs["serve_config"].value
    ignition_hash = up_result.outputs["ignition_hash"].value
    public_config_stdout = up_result.outputs["public_config_stdout"].value

    # Verify the hash is in the serve_config request_header
    assert serve_config["request_header"]["Verification-Hash"] == ignition_hash

    # Verify the hash is in the public_config ignition output
    public_config_json = json.loads(public_config_stdout)
    ignition_replace = public_config_json["ignition"]["config"]["replace"]
    assert ignition_replace["verification"]["hash"] == ignition_hash
    assert (
        ignition_replace["httpHeaders"][0]["value"]
        == ignition_hash
    )
