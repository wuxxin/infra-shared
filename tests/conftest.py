import os
import shutil
import subprocess
from pathlib import Path
import pytest
from pulumi.automation import create_or_select_stack, LocalWorkspace, UpResult, Stack, LocalWorkspaceOptions

@pytest.fixture(scope="session")
def project_root():
    """Returns the root directory of the infra-shared project."""
    return Path(__file__).parent.parent

@pytest.fixture(scope="session")
def test_project_dir(tmpdir_factory):
    """Creates a temporary directory for the test project and returns its Path."""
    return Path(tmpdir_factory.mktemp("infra-test-project"))

@pytest.fixture(scope="session")
def pulumi_project_dir(test_project_dir, project_root):
    """
    Initializes a new Pulumi project in the temporary directory by running
    the create_skeleton.sh script.
    """
    project_path = test_project_dir / "project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)

    # Run create_skeleton.sh
    create_skeleton_script = project_root / "scripts" / "create_skeleton.sh"
    cmd = [
        str(create_skeleton_script),
        "--project-dir", str(project_path),
        "--name-library", "infra",
        "--yes"
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # The skeleton script assumes it's a submodule, but for tests, we symlink it.
    infra_symlink = project_path / "infra"
    if not infra_symlink.exists():
        infra_symlink.symlink_to(project_root)

    # The Pulumi project needs access to the virtual environment of the main project.
    # We'll update Pulumi.yaml to point to it.
    pulumi_yaml_path = project_path / "Pulumi.yaml"
    pulumi_yaml_content = pulumi_yaml_path.read_text()

    # Calculate relative path to the main project's .venv
    main_venv_path = project_root / ".venv"
    if main_venv_path.exists():
        relative_venv_path = os.path.relpath(main_venv_path, project_path)
        updated_yaml_content = pulumi_yaml_content.replace(
            "virtualenv: .venv", f"virtualenv: {relative_venv_path}"
        )
        pulumi_yaml_path.write_text(updated_yaml_content)

    # Copy config-template.yaml to Pulumi.sim.yaml for the 'sim' stack
    config_template = project_path / "config-template.yaml"
    sim_config_path = project_path / "Pulumi.sim.yaml"
    shutil.copy(config_template, sim_config_path)

    # For tests, we don't want to protect the CA root cert, so it can be destroyed.
    with sim_config_path.open("a") as f:
        f.write("\n  ca_protect_rootcert: false\n")

    return project_path

@pytest.fixture(scope="session")
def pulumi_stack(pulumi_project_dir) -> UpResult:
    """
    This fixture sets up a Pulumi stack for the entire test session.
    It creates the stack, runs `pulumi up`, yields the result to the tests,
    and then tears down the stack.
    """
    stack_name = "sim"
    work_dir = str(pulumi_project_dir)

    # Use a local filesystem backend for Pulumi state, stored within the test project dir
    pulumi_home = pulumi_project_dir / "state" / "pulumi"
    pulumi_home.mkdir(parents=True, exist_ok=True)

    env_vars = {
        "PULUMI_CONFIG_PASSPHRASE": "sim",
        "PULUMI_BACKEND_URL": f"file://{pulumi_home}"
    }

    print(f"Setting up Pulumi stack: {stack_name} in {work_dir}")
    stack = None
    try:
        opts = LocalWorkspaceOptions(
            work_dir=work_dir,
            env_vars=env_vars,
        )

        stack = create_or_select_stack(
            stack_name=stack_name,
            work_dir=work_dir,
            opts=opts,
        )

        print("Running `pulumi up`...")
        up_result = stack.up(on_output=print)
        print("`pulumi up` complete.")

        yield up_result

    finally:
        print(f"Tearing down Pulumi stack: {stack_name}...")
        if stack:
            stack.destroy(on_output=print)
            stack.workspace.remove_stack(stack_name)
        print("Teardown complete.")
