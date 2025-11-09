import pytest
from pulumi.automation import Stack, ConfigValue
from .utils import add_pulumi_program, assert_file_exists


def test_authority_import_pulumi(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    """
    Tests that the Pulumi stack can be successfully brought up with the
    authority module using the Pulumi backend.
    """
    pulumi_stack.set_config("ca_create_using_vault", ConfigValue("false"))
    up_result = pulumi_stack.up(**pulumi_up_args)
    # The main test is the successful execution of the pulumi_stack fixture.
    # We can add a simple assertion to confirm the stack has outputs.
    assert up_result.outputs is not None
    assert up_result.outputs["ca_factory"].value["ca_type"] == "pulumi"


def test_authority_import_vault(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    """
    Tests that the Pulumi stack can be successfully brought up with the
    authority module using the Vault backend.
    """
    pulumi_stack.set_config("ca_create_using_vault", ConfigValue("true"))
    up_result = pulumi_stack.up(**pulumi_up_args)
    # The main test is the successful execution of the pulumi_stack fixture.
    # We can add a simple assertion to confirm the stack has outputs.
    assert up_result.outputs is not None
    assert up_result.outputs["ca_factory"].value["ca_type"] == "vault"
