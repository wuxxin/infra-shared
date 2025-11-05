import os
import shutil
import subprocess
from pathlib import Path
import pytest
from pulumi.automation import (
    create_or_select_stack,
    UpResult,
    LocalWorkspaceOptions,
    Stack,
    LocalWorkspace,
)


@pytest.fixture(scope="session")
def project_root():
    """Returns the root directory of the infra-shared project."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_project_dir(tmp_path_factory):
    """Creates a temporary directory for the test project and returns its Path."""
    return tmp_path_factory.mktemp("infra-test-project")


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
        "--project-dir",
        str(project_path),
        "--name-library",
        "infra",
        "--yes",
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # The skeleton script assumes it's a submodule, but for tests, we copy it.
    infra_path = project_path / "infra"
    shutil.copytree(
        project_root,
        infra_path,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "build"),
        dirs_exist_ok=True,
        symlinks=False,
    )

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

    return project_path


@pytest.fixture(scope="function")
def pulumi_stack_config():
    """
    Default configuration for the Pulumi stack.
    This can be overridden in individual tests.
    """
    return {"stack_name": "sim", "add_conf": ""}


@pytest.fixture(scope="function")
def pulumi_up_args():
    return {
        "on_output": print,
        "on_error": print,
        "suppress_progress": True,
        "suppress_outputs": False,
        "log_to_std_err": True,
        "log_flow": True,
        "color": False,
        "log_verbosity": 3,
        "debug": True,
    }


@pytest.fixture(scope="function")
def pulumi_stack(pulumi_project_dir, pulumi_stack_config) -> Stack:
    """
    This fixture sets up a Pulumi stack for each test function.
    It creates the stack, yields it to the test, and then tears it down.
    """
    stack_name = pulumi_stack_config["stack_name"]
    add_conf = pulumi_stack_config["add_conf"]
    work_dir = str(pulumi_project_dir)

    # Pulumi state, stored within the test project dir
    pulumi_home = pulumi_project_dir / "state" / "pulumi"
    pulumi_home.mkdir(parents=True, exist_ok=True)

    # Copy config-template.yaml to Pulumi.sim.yaml for the 'sim' stack
    config_template = pulumi_project_dir / "config-template.yaml"
    stack_config_path = pulumi_project_dir / f"Pulumi.{stack_name}.yaml"
    shutil.copy(config_template, stack_config_path)

    # add custom conf and don't protect the CA root cert for tests
    with stack_config_path.open("a") as f:
        f.write(f"\n  ca_protect_rootcert: false\n{add_conf}\n")

    env_vars = {
        "PULUMI_CONFIG_PASSPHRASE": "test",
        "PULUMI_BACKEND_URL": f"file://{pulumi_home}",
    }

    print(f"Setting up Pulumi stack: {stack_name} in {work_dir}")
    stack = None
    try:
        opts = LocalWorkspaceOptions(work_dir=work_dir, env_vars=env_vars)
        stack = create_or_select_stack(stack_name=stack_name, work_dir=work_dir, opts=opts)
        print("Yielding stack to test.")
        yield stack

    finally:
        print(f"Tearing down Pulumi stack: {stack_name}...")
        if stack:
            stack.destroy(on_output=print)
            stack.workspace.remove_stack(stack_name)
        print("Teardown complete.")
