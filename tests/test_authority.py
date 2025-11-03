from pulumi.automation import Stack
from .utils import add_pulumi_program, assert_file_exists

def test_authority_import(pulumi_stack: Stack, pulumi_project_dir):
    """
    Tests that the Pulumi stack can be successfully brought up with just an
    import of the authority module.
    """
    up_result = pulumi_stack.up(on_output=print)
    # The main test is the successful execution of the pulumi_stack fixture.
    # We can add a simple assertion to confirm the stack has outputs.
    assert up_result.outputs is not None
