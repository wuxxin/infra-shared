from pulumi.automation import UpResult
from .utils import add_pulumi_program, assert_file_exists

def test_authority_import(pulumi_stack: UpResult, pulumi_project_dir):
    """
    Tests that the Pulumi stack can be successfully brought up with just an
    import of the authority module.
    """
    # The main test is the successful execution of the pulumi_stack fixture.
    # We can add a simple assertion to confirm the stack has outputs.
    assert pulumi_stack.outputs is not None
