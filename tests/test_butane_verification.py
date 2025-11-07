
import os
import yaml
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

pulumi.export("serve_config", serve_config.config)
pulumi.export("public_config", public_config.ignition_config)
pulumi.export("ignition_hash", host_config.ignition_config_hash)

"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # 1. Verify the hash is in the serve_config request_header
    serve_config = up_result.outputs["serve_config"].value
    ignition_hash = up_result.outputs["ignition_hash"].value
    assert "request_header" in serve_config
    assert "Verification-Hash" in serve_config["request_header"]
    assert serve_config["request_header"]["Verification-Hash"] == ignition_hash

    # 2. Verify the hash is in the public_config ignition output
    public_config_str = up_result.outputs["public_config"].value
    public_config = yaml.safe_load(public_config_str)

    # The 'butane' tool has a bug and does not support http_headers correctly.
    # We work around this by checking the parts of the config that are generated
    # correctly and then manually verifying the header logic.

    # Check for source and verification hash, which are correctly generated
    assert "ignition" in public_config
    assert "config" in public_config["ignition"]
    assert "replace" in public_config["ignition"]["config"]
    replace_config = public_config["ignition"]["config"]["replace"]

    assert "source" in replace_config
    assert "verification" in replace_config
    assert "hash" in replace_config["verification"]
    assert replace_config["verification"]["hash"] == ignition_hash

    # Verify the hash is in the public_config ignition output
    public_config_str = up_result.outputs["public_config"].value
    public_config = yaml.safe_load(public_config_str)
    assert "ignition" in public_config
    assert "config" in public_config["ignition"]
    assert "replace" in public_config["ignition"]["config"]
    replace_config = public_config["ignition"]["config"]["replace"]
    assert "verification" in replace_config
    assert "hash" in replace_config["verification"]
    assert replace_config["verification"]["hash"] == ignition_hash
    assert "httpHeaders" in replace_config
    headers = replace_config["httpHeaders"]
    assert any(
        h["name"] == "Verification-Hash" and h["inline"] == ignition_hash for h in headers
    ), "Verification-Hash header not found or incorrect"
