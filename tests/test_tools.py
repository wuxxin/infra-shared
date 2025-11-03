import pytest
from pulumi.automation import Stack
import pulumi
from .utils import add_pulumi_program, assert_file_exists
import os


def test_ssh_functions_with_pulumi_outputs(pulumi_stack: Stack, pulumi_project_dir):
    program = """
import pulumi
from infra import tools
import os

# Create a dummy file to be used as a source for ssh_put
with open("test_file.txt", "w") as f:
    f.write("hello")

# Test ssh_put with string and pulumi.Output
tools.ssh_put(
    "test_put",
    "localhost",
    "user",
    files={
        "/remote/path1": "test_file.txt",
        "/remote/path2": pulumi.Output.from_input("test_file.txt"),
        # pulumi.Output.from_input("/remote/path3"): pulumi.Output.from_input("test_file.txt"),
    },
    simulate=True,
)

# Test ssh_get with string and pulumi.Output
tools.ssh_get(
    "test_get",
    "localhost",
    "user",
    files={
        "/remote/path4": "local_path1",
        "/remote/path5": pulumi.Output.from_input("local_path2"),
        # pulumi.Output.from_input("/remote/path6"): pulumi.Output.from_input("local_path3"),
    },
    simulate=True,
)

# Test ssh_deploy with string and pulumi.Output
tools.ssh_deploy(
    "test_deploy",
    "localhost",
    "user",
    files={
        "/remote/path6": "some_data1",
        "/remote/path7": pulumi.Output.from_input("some_data2"),
        # pulumi.Output.from_input("/remote/path8"): pulumi.Output.from_input("some_data3"),
    },
    simulate=True,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(on_output=print)
    assert up_result.summary.result == "succeeded"

    # Assert that the simulated files were created
    tmpdir = os.path.join(pulumi_project_dir, "build", "tmp", "sim")

    # ssh_put assertions
    assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path1"))
    assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path2"))
    # assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path3"))

    # ssh_get assertions
    # In simulate mode, ssh_get also creates local files
    assert os.path.exists(os.path.join(tmpdir, "get__remote_path4"))
    assert os.path.exists(os.path.join(tmpdir, "get__remote_path5"))
    # assert os.path.exists(os.path.join(tmpdir, "get__remote_path6"))

    # ssh_deploy assertions
    assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path6"))
    assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path7"))
    # assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path8"))
