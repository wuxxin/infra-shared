# Workpad

Read `docs/agent-workflow.md`, `docs/development.md` and `README.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.
Read and Update `docs/tasks.md` under Section "Planned Tasks" with the detailed description of that tasks.
Then, do each of the described tasks one by one, and update `docs/tasks.md` accordingly.

Required changes:


- Add basic test and fixtures with pytest
  - use `make pytest` to run pytest
  - analyse `Makefile` target `sim-test` and `scripts/create_skeleton.sh` to recreate the sim-test setup and make pytest fixtures for a pytest pulumi stack test that will get different tests added to the stack. the stack is then tested with equivalent of `pulumi up --stack sim` meaning the fixtures will always create , prefill a sim stack.
  - first test is a plain import of `authority.py`, and the sucessful result of running pulumi up equivalent.
  - in addition to session fixtures there should be a function for easy includes of python into main to be tested as stack, to run a stack with includes you like
  - the authority.py test is just a empty setup
  - please use pulumi programatically for execution and also for checking expected stack results.
  - there should be a function to assert for files in the current state/files/sim dir , for easy access of files output

Example for using pulumi in pytest programatically:
`'`py
import pytest
import os
from pulumi.automation import (
    create_or_select_stack,
    LocalWorkspace,
    UpResult,
    Stack
)

@pytest.fixture(scope="session")
def pulumi_stack() -> UpResult:
    """
    This is a pytest fixture that creates and manages a Pulumi stack
    for the entire test session.

    - scope="session": Ensures this fixture runs only ONCE per pytest session.
      The stack is created before any tests run and destroyed after
      all tests are complete. This is crucial for infrastructure tests
      to avoid slow setup/teardown for every single test function.
    """

    # --- Configuration ---
    stack_name = "pytest_session_stack"

    # Calculate path to the 'pulumi_project' directory, which is
    # one level up and then into 'pulumi_project'
    project_dir = os.path.join(
        os.path.dirname(__file__),  # 'tests' directory
        "..",                       # project root
        "pulumi_project"            # 'pulumi_project' directory
    )

    print(f"\nSetting up Pulumi stack: {stack_name}...")
    print(f"Project directory: {os.path.abspath(project_dir)}")

    # --- Setup ---
    try:
        # Use LocalWorkspace to select the project
        workspace = LocalWorkspace(work_dir=project_dir)

        # Create or select the stack
        stack: Stack = create_or_select_stack(
            stack_name=stack_name,
            workspace=workspace
        )

        # Run `pulumi up`
        # We pass on_output=print to stream the Pulumi logs to stdout
        up_result: UpResult = stack.up(on_output=print)
        print("Stack setup complete.")

        # --- Yield to Tests ---
        # The 'yield' statement passes the up_result to the test functions
        # and pauses the fixture here until all tests are done.
        yield up_result

    finally:
        # --- Teardown ---
        # This code runs after all tests in the session are complete.
        print(f"\nTearing down Pulumi stack: {stack_name}...")

        # Ensure 'stack' was initialized before trying to destroy
        if 'stack' in locals():
            # Run `pulumi destroy`
            stack.destroy(on_output=print)
            print("Stack destroy complete.")

            # Clean up the stack entirely from the Pulumi backend
            stack.workspace.remove_stack(stack_name)
            print("Stack removed from workspace.")

        print("Teardown complete.")


# --- Test Functions ---

def test_stack_outputs_exist(pulumi_stack: UpResult):
    """
    Tests that the expected output keys exist.
    The 'pulumi_stack' argument tells pytest to inject the
    UpResult object from our fixture.
    """
    assert "message_output" in pulumi_stack.outputs
    assert "website_url" in pulumi_stack.outputs

def test_message_output_value(pulumi_stack: UpResult):
    """
    Tests the specific value of the 'message_output'.
    """
    expected_message = "Hello from Pulumi!"
    actual_message = pulumi_stack.outputs["message_output"].value
    assert actual_message == expected_message

def test_website_url_value(pulumi_stack: UpResult):
    """
    Tests the specific value of the 'website_url'.
    """
    expected_url = "https.example.com"
    actual_url = pulumi_stack.outputs["website_url"].value
    assert actual_url == expected_url
```
