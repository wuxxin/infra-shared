import shutil
from pathlib import Path
from pulumi.automation import Stack


def test_fake_ca_example(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    """
    Test the fake_ca example
    """

    # Copy the __init__.py from examples/fake_ca into the pulumi_project_dir
    shutil.copy(
        Path("examples/fake_ca/__init__.py"),
        pulumi_project_dir,
    )

    # Rename the copied __init__.py to __main__.py to make it the Pulumi program entry point
    shutil.move(pulumi_project_dir / "__init__.py", pulumi_project_dir / "__main__.py")

    # Run the Pulumi program
    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # Assert on specific outputs
    assert "fake_ca_factory" in up_result.outputs
    assert "fake_ca_mitm_ca" in up_result.outputs
    assert "fake_mitm_host" in up_result.outputs
