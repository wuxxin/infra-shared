"""Tests for LocalSaltCall Pulumi component."""

from pathlib import Path

from pulumi.automation import Stack

from .utils import add_pulumi_program


def test_local_salt_call_ping(
    pulumi_stack: Stack, pulumi_project_dir: Path, pulumi_up_args: dict
):
    """Tests executing a basic ping call via LocalSaltCall."""
    program = """
import pulumi
from infra.tools import LocalSaltCall

salt_call = LocalSaltCall(
    "test_ping",
    "test.ping",
    opts=pulumi.ResourceOptions(additional_secret_outputs=["stdout"]),
)
pulumi.export("stdout", salt_call.result.stdout)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # Verify stdout contains successful salt-call response
    assert "stdout" in up_result.outputs
    assert "True" in up_result.outputs["stdout"].value

    # Verify generated Salt minion config and structure
    salt_root = pulumi_project_dir / "build" / "salt" / "sim" / "test_ping"
    minion_conf = salt_root / "minion"
    pillar_top = salt_root / "pillar" / "top.sls"
    pillar_main = salt_root / "pillar" / "main.sls"

    assert minion_conf.exists()
    assert pillar_top.exists()
    assert pillar_main.exists()


def test_local_salt_call_state_with_pillar(
    pulumi_stack: Stack, pulumi_project_dir: Path, pulumi_up_args: dict
):
    """Tests executing an SLS state with pillar data via LocalSaltCall."""
    # Prepare custom SLS directory and state file
    sls_dir = pulumi_project_dir / "custom_sls"
    sls_dir.mkdir(parents=True, exist_ok=True)
    target_file = pulumi_project_dir / "build" / "salt_test_output.txt"

    state_file = sls_dir / "managed_test.sls"
    state_file.write_text(
        f"""
create_managed_file:
  file.managed:
    - name: {target_file}
    - contents: "{{{{ pillar['test_message'] }}}}"
    - makedirs: True
"""
    )

    program = f"""
import pulumi
from infra.tools import LocalSaltCall

salt_call = LocalSaltCall(
    "test_state",
    "state.sls",
    "managed_test",
    pillar={{"test_message": "tdd_salt_success"}},
    sls_dir="{sls_dir}",
    opts=pulumi.ResourceOptions(additional_secret_outputs=["stdout"]),
)
pulumi.export("stdout", salt_call.result.stdout)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    # Verify pillar was written to main.sls
    salt_root = pulumi_project_dir / "build" / "salt" / "sim" / "test_state"
    pillar_main = salt_root / "pillar" / "main.sls"
    assert pillar_main.exists()
    assert "tdd_salt_success" in pillar_main.read_text()

    # Verify the Salt state created the target file with expected contents
    assert target_file.exists()
    assert target_file.read_text().strip() == "tdd_salt_success"
