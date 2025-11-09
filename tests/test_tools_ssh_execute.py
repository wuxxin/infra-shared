import os
import pytest
from pulumi.automation import Stack
from .utils import add_pulumi_program


def test_ssh_execute_simulate(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    program = """
import pulumi
from infra import tools
import os

tools.ssh_execute(
    "test_execute",
    "localhost",
    "user",
    cmdline="echo 'hello world'",
    simulate=True,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    tmpdir = os.path.join(pulumi_project_dir, "build", "tmp", "sim")
    expected_file = os.path.join(tmpdir, "test_execute_ssh_execute")
    assert os.path.exists(expected_file)
    with open(expected_file, "r") as f:
        assert f.read() == "echo 'hello world'"


def test_ssh_execute_live(
    pulumi_stack: Stack,
    pulumi_project_dir,
    pulumi_up_args,
    robust_ssh_server,
):
    output_file = "/tmp/ssh_execute_test_output"
    robust_ssh_server.start()
    robust_ssh_server.add_file(output_file)

    program = f"""
import pulumi
from infra import tools
from infra.authority import ssh_factory

tools.ssh_execute(
    "test_execute_live",
    "{robust_ssh_server.host}",
    "testuser",
    cmdline="readlink -e {output_file}",
    simulate=False,
    port={robust_ssh_server.port},
    opts=pulumi.ResourceOptions(additional_secret_outputs=["stdout", "stderr"]),
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # The robust_ssh_server fixture doesn't actually execute commands, so we can't check for the output file.
    # Instead, we just check that the Pulumi program ran successfully.
    # To properly test this, we would need a more advanced mock SSH server.
    # For now, we are just testing that the component doesn't crash.
