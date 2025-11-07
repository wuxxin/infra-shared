import os

from pulumi.automation import Stack
from .utils import add_pulumi_program, assert_file_exists


def test_ssh_functions_with_pulumi_outputs(
    pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args
):
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
        pulumi.Output.from_input("/remote/path3"): pulumi.Output.from_input("test_file.txt"),
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
        pulumi.Output.from_input("/remote/path6"): pulumi.Output.from_input("local_path3"),
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
        pulumi.Output.from_input("/remote/path8"): pulumi.Output.from_input("some_data3"),
    },
    simulate=True,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # Assert that the simulated files were created
    tmpdir = os.path.join(pulumi_project_dir, "build", "tmp", "sim")

    # ssh_put assertions
    assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path1"))
    assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path2"))
    assert os.path.exists(os.path.join(tmpdir, "test_put_put__remote_path3"))

    # ssh_get assertions
    # In simulate mode, ssh_get also creates local files
    assert os.path.exists(os.path.join(tmpdir, "test_get_get__remote_path4"))
    assert os.path.exists(os.path.join(tmpdir, "test_get_get__remote_path5"))
    assert os.path.exists(os.path.join(tmpdir, "test_get_get__remote_path6"))

    # ssh_deploy assertions
    assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path6"))
    assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path7"))
    assert os.path.exists(os.path.join(tmpdir, "test_deploy_deploy__remote_path8"))


def test_ssh_deploy_content(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    """
    Tests that ssh_deploy correctly deploys files with distinct content.
    """
    program = """
import pulumi
from infra import tools
import os

files_to_deploy = {
    "/remote/test1.txt": "content1",
    "/remote/test2.txt": "content2",
    "/remote/test3.txt": "content3",
}

tools.ssh_deploy(
    "test_deploy_content",
    "localhost",
    "user",
    files=files_to_deploy,
    simulate=True,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    tmpdir = os.path.join(pulumi_project_dir, "build", "tmp", "sim")

    # Assert that the simulated files were created and have the correct content
    with open(os.path.join(tmpdir, "test_deploy_content_deploy__remote_test1.txt"), "r") as f:
        assert f.read() == "content1"
    with open(os.path.join(tmpdir, "test_deploy_content_deploy__remote_test2.txt"), "r") as f:
        assert f.read() == "content2"
    with open(os.path.join(tmpdir, "test_deploy_content_deploy__remote_test3.txt"), "r") as f:
        assert f.read() == "content3"
