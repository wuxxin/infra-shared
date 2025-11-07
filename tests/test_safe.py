import pytest
import shutil
from pathlib import Path
from pulumi.automation import Stack


@pytest.fixture(scope="function")
def pulumi_stack_config(pulumi_project_dir):
    """Override the default stack config for this test."""
    return {
        "stack_name": "sim",
        "add_conf": f"\n  {pulumi_project_dir.name}:safe_showcase_unittest: true\n",
    }


def test_safe_example(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    """
    Test the safe example
    """

    # Copy the entire examples/safe directory into the pulumi_project_dir
    shutil.copytree(
        Path("examples/safe"),
        pulumi_project_dir,
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )

    # Rename the copied __init__.py to __main__.py to make it the Pulumi program entry point
    shutil.move(pulumi_project_dir / "__init__.py", pulumi_project_dir / "__main__.py")

    # Run the Pulumi program
    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # Assert on specific outputs
    assert "safe_host_update" in up_result.outputs
    assert up_result.outputs["safe_host_update"].value["simulate"] == True
