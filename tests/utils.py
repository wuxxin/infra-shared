from pathlib import Path


def assert_file_exists(base_dir: Path, file_path: str):
    """
    Asserts that a file exists at a given path relative to a base directory.

    Args:
        base_dir: The base directory to check from.
        file_path: The relative path to the file.
    """
    full_path = base_dir / file_path
    assert full_path.is_file(), f"Expected file does not exist: {full_path}"


def add_pulumi_program(pulumi_project_dir: Path, program_code: str):
    """
    Writes a given string of Python code to the __main__.py of a Pulumi project.

    Args:
        pulumi_project_dir: The path to the Pulumi project directory.
        program_code: A string containing the Python code to add.
    """
    main_py_path = pulumi_project_dir / "__main__.py"
    with main_py_path.open("w") as f:
        f.write(f"\n{program_code}\n")
