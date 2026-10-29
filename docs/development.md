# Development

## Source Code

The Source Code and the Issue Tracker is at [github.com/wuxxin/infra-shared](https://github.com/wuxxin/infra-shared).

It is licenced under the [Apache 2.0 License](https://github.com/wuxxin/infra-shared/blob/main/LICENSE).

## Files and Directories Layout

### Development Documents

- `docs/development.md`: (This file) The project file layout, architectural overview, developer and agent guidelines
- `docs/marimo-development.md`: if present, Developer Guidelines for working with marimo notebooks
- `docs/tasks.md`: A living document tracking tasks of types already completed, newly discovered, to be done, and tracking memories about discovered relations

### User Documentation

- `README.md`: A user centric view on howto use the project
- `docs/`:  mkdocs documentation

CoreOS related:

- `docs/os.md` and `docs/update.md` for coreos system and system update
- `docs/networking.md` for coreos system network configuration
- `docs/credentials.md` for credentials configuration in coreos and usage in container, compose and nspawn workloads
- `docs/healthchecks.md` for healtheck configuration of container, compose and nspawn workloads
- `docs/butane.md` for jinja templating butane and saltstack generation

Pulumi Resources related:

- `docs/pulumi.md` for pulumi components

Development Scripts:

- `docs/scripts.md` for documentation of scripts inside directory `scripts/`:

## Development Commands & Lifecycle

All development tasks within `infra` (and downstream repositories) are orchestrated using `make` and Python `uv`.

### Environment Setup

```bash
# Verify and install OS-level dependencies (Arch/Manjaro, Debian/Ubuntu, or container)
make provision-local

# Build virtual environment (.venv) and synchronize all extras using pinned Python 3.13+
make buildenv

# Clean virtual environment and build artifacts
make buildenv-clean
make py-clean
```

The build system pins Python via `PYTHON ?= /usr/bin/python3`, invoking `uv lock --python $(PYTHON)` and `uv venv --python $(PYTHON)` to ensure stable virtualenv creation across environments.

### Testing & Quality Assurance

```bash
# Run all pytest suites
make pytest

# Run a specific test module
make pytest args="tests/test_authority.py"

# Run tests matching an expression with verbose output
make pytest args="-k test_tools -v"

# Run combined test-all pipeline (online docs build followed by pytest)
make test-all

# Run test suite inside an isolated container
make test-all-container
```

### Code Quality & Linting

```bash
# Lint source code using Ruff
uv run ruff check .

# Automatically format code using Ruff (configured line length: 95)
uv run ruff format .

# Static type checking using Pyright
uv run pyright
```

### Documentation

```bash
# Build local documentation into build/docs-local/
make docs

# Serve documentation with live reload at http://127.0.0.1:8000
make docs-serve

# Build online documentation bundle into build/docs-online/
make docs-online-build

# Clean documentation artifacts
make docs-clean
```

### Pulumi Stack Operations

Workflows operate on either the `sim` (local simulation / Libvirt) or `prod` (production) stack:

```bash
# Simulation Stack (local KVM/simulation or offline validation)
make sim-create         # Initialize 'sim' stack with passphrase 'sim'
make sim-preview        # Preview infrastructure plan for simulation
make sim-up             # Apply infrastructure changes to simulation
make sim-show           # Export current simulation state as JSON
make sim-clean          # Destroy resources and clean up simulation stack
make sim__ args="<cmd>" # Run arbitrary Pulumi CLI command on simulation stack

# Production Stack (encrypted with age prod_passphrase.age)
make prod-create        # Initialize 'prod' stack
make prod-preview       # Preview infrastructure plan for production
make prod-up            # Apply infrastructure changes to production
make prod__ args="<cmd>" # Run arbitrary Pulumi CLI command on production
```

### Makefile Target Summary

| command | description |
| --- | --- |
| `buildenv` | Build python virtual environment and sync dependencies |
| `buildenv-clean` | Remove build environment artifacts and `.venv` |
| `clean` | Remove all build and test artifacts |
| `docs` | Build docs for local usage into `build/docs-local` |
| `docs-clean` | Remove all generated documentation |
| `docs-online-build` | Build docs for static web serving into `build/docs-online` |
| `docs-serve` | Rebuild and serve docs with autoreload on port 8000 |
| `provision-container` | Build dependencies for provisioning using a container |
| `provision-local` | Check and install system prerequisites via `scripts/provision_requirements.sh` |
| `py-clean` | Remove python related bytecode and cache artifacts |
| `pytest` | Run tests using `pytest $(args)` |
| `pytest-clean` | Remove pytest cache and coverage artifacts |
| `sim__` | Run arbitrary Pulumi CLI command on simulation stack |
| `test-all` | Run complete pipeline: `docs-online-build` + full `pytest` |
| `test-all-container` | Run complete pipeline inside isolated container |
### Tools used

- `pulumi` - imperativ infrastructure declaration using python
- `fcos` - Fedora-CoreOS, minimal OS with `clevis` (sss,tang,tpm) storage unlock
- `butane` - create fcos `ignition` configs using `jinja` enhanced butane yaml
- `systemd` - service, socker, path, timer, nspawn machine container
- `podman` - build Container and NSpawn images, run Container using quadlet systemd container
- `saltstack`
    - local build environments and local services
    - remote fcos config update using butane to saltstack translation and execution
- `mkdocs` - documentation using markdown and mermaid
- `libvirt` - simulation of machines using the virtualization api supporting qemu and kvm
- `tang` - server used for getting a key shard for unattended encrypted storage unlock on boot
- `age` - ssh keys based encryption of production files and pulumi master password
- `uv`- virtualenv management using pyproject.toml and uv.lock

## Architecture Style Objectives

- **avoid legacy** technologies, build a clear **chain of trust**, support **encrypted storage** at rest
    - use **ssh keys** as root of trust for pulumi **stack secret** using **age**
    - store **secrets in the repository** using pulumi config secrets
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
- create **disposable/immutable-ish** infrastructure, aim for **structural isolation** and reusability
- treat **state as code**, favor **state reconciliation** tools
    - have the **complete encrypted state** in the **git repository** as **single source of truth**
- have a **big/full featured provision client** as the center of operation
    - target one **provision os** and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable local **simulation environment** with **fast reconfiguration** turnaround
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **marimo notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**

## Python Style, Conventions and preferred libraries

- **Use uv** (the virtual environment and package manager) whenever executing Python commands, including for unit tests. Never invoke `pip` directly.
- **Python Runtime**: Minimum Python 3.13 (`requires-python = ">=3.13"`). Use native generic syntax (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`).
- **Use `pyproject.toml`** to declare dependencies.
- **Line Length & Formatting**: Max 95 characters. Use `uv run ruff format .` and `uv run ruff check .`.
- **Type Checking**: Use `uv run pyright` for static type validation.
- **Use python_dotenv and load_env()** for environment variables.
- **Use `pydantic` for data validation**.
- **Use `pytest` for testing**, `playwright` with headless chromium and `pytest-playwright` for gui testing.
- **Use `FastAPI` for APIs**.
- **Use `FastHTML` for HTML**.
- **Use `SQLAlchemy` or `SQLModel` for ORM**.
- **Before adding a new library, look in `pyproject.toml`** if there is already a fitting library to use.
- Write **docstrings for every function** using the Google style:

  ```python
  def example(param1: str) -> bool:
      """
      Brief summary.

      Args:
          param1 (str): Description.
      Returns:
          bool: Description.
      """
  ```

### Testing Architecture & TDD Workflow

The test suite in `tests/` uses **pytest** combined with the **Pulumi Automation API** (`pulumi.automation.Stack`) to run reproducible integration tests against isolated local file-backed state workspaces.

#### Core Fixtures (`tests/conftest.py`)
- **`pulumi_stack`**: Initializes a temporary Pulumi stack (`sim`), configures file-backed state under `state/pulumi`, yields the stack to the test, and guarantees teardown via `stack.destroy()` in a `finally` block.
- **`pulumi_project_dir`**: Dynamically creates a temporary Git repository, executes `scripts/create_skeleton.sh`, and links the project's virtualenv to the active test runner.
- **`robust_ssh_server`**: In-process multi-threaded Paramiko SSH server running on `127.0.0.1` capable of simulating server latency, connection loss, and authentication behavior.

#### Writing New Tests
1. **Use `utils.add_pulumi_program`**: Define minimal Pulumi test programs inline:
   ```python
   from tests.utils import add_pulumi_program

   add_pulumi_program(
       pulumi_project_dir,
       """
   import pulumi
   from infra.authority import CACertFactory
   ca = CACertFactory("test_ca")
   pulumi.export("ca_cert", ca.root_cert_pem)
   """,
   )
   ```
2. **Execute and Assert**:
   ```python
   up_result = pulumi_stack.up(**pulumi_up_args)
   assert up_result.summary.result == "succeeded"
   assert "ca_cert" in up_result.outputs
   ```
3. **Prefer Simulation for File/SSH Tests**: Set `simulate=True` when validating `SSHPut` or `SSHDeploy` to inspect output files under `build/tmp/sim/` without spawning network sockets.

#### Test-Driven Development (TDD) Red-Green-Refactor Pattern
- **Red (Write Failing Specification First)**:
  - Formulate minimal Pulumi test scripts via `add_pulumi_program(pulumi_project_dir, code)`.
  - Assert on external observable artifacts (e.g. generated files in `build/`, exported Pulumi outputs, exit codes) rather than internal implementation details or private dictionaries.
  - Run the targeted test: `make pytest args="tests/test_<feature>.py"`.
  - Verify the test fails specifically due to the absent feature or broken contract.
- **Green (Minimal Working Implementation)**:
  - Implement the minimal declarative resources (`ComponentResource`, `command.local.Command`, etc.) required to satisfy the assertion.
  - Verify the targeted test suite passes cleanly.
- **Refactor & Mutation Check**:
  - Keep files under 800 lines; format with `uv run ruff format .` (95 max line length); type-check with `uv run pyright`.
  - Perform mutation checks: simulate erroneous branches, missing configurations, or broken paths and verify that tests fail accordingly.
  - Run the full suite with `make test-all` (combining docs build and complete pytest suite).

#### Test Component File & Runtime Conventions
- **`SSHPut` and `SSHDeploy`** in simulation mode write files named after their sub-resource identity (`<prefix>_<remote_path_sanitized>`) under `build/tmp/sim/`.
- **`SSHGet`** in simulation mode targets the specified `local_dir` or `build/tmp/<stack>/` and writes directly to the destination local file path (`full_local_path_output`), preserving local filesystem semantics.
- **`LocalSaltCall`** (`infra/tools.py`, tested in `tests/test_localsaltcall.py`) generates isolated minion configurations in `build/salt/<stack>/<resource_name>/` with dedicated `sls` and `pillar` trees, allowing full unprivileged execution of local Salt modules (`test.ping`, `pillar.items`, `state.sls`).
- **Environment & Plugin Isolation**: Pytest configuration in `pyproject.toml` sets `addopts = "-p no:pylama"` to prevent host environment plugin conflicts (e.g., deprecated hooks from system `pylama` on Python 3.14).
## Project Memory

### Project Overview

- **Project Name**: The project's name is 'infra-shared'.
- **Core Technologies**: This repository is a 'Software Defined Git Operated Infrastructure' project for managing home infrastructure using Pulumi, Fedora Coreos, and Python.
- **Workload Types**: The project manages different workload types: single containers (defined by `.container` files), Docker Compose services (`compose.yml`), and systemd-nspawn machines (`.nspawn` files).

### Pulumi

- **Component Resources**: Pulumi component resources that receive an `Output` as a property (e.g., an `Output[dict]`) must perform operations like iteration on that property within an `.apply()` block to ensure the value is resolved before being used.
- **Configuration**: Pulumi configuration in Python, using `pulumi.Config().get('key')`, automatically namespaces the key with the project name from `Pulumi.yaml`. A call to `config.get('my_key')` for project `my_project` looks for the YAML entry `my_project:my_key`.
- **Child Resources**: When creating a child resource within a Pulumi component where a handle to the resource object is not needed later in the code, the idiomatic pattern is to assign the instantiation to `_` (e.g., `_ = command.remote.Command(...)`). The resource's lifecycle is managed by Pulumi as long as `parent=self` is set in its options.
- **Outputs as Dictionary Keys**: In Pulumi, an `Output` object cannot be used as a dictionary key. The dictionary must be constructed inside a `.apply()` block after the `Output`s for the keys have been resolved to concrete values.
- **Serialization Errors**: When creating resources inside a `.apply()` block within a Pulumi component, accessing component attributes like `self.props` can lead to serialization errors (`KeyError`). A more reliable pattern is to use lexical closure to capture variables (like the `props` dictionary) from the `__init__` method's scope directly.
- **Dynamic Resources**: Pulumi Dynamic Resources, like `WaitForHostReadyProvider` in `tools.py`, must explicitly import all their dependencies (e.g., `uuid`, `time`) within the module scope, as they are serialized and executed in a separate context.

### Testing

- **Test Environment**: if make pytest fails, try to recreate the buildenv with `. .venv/bin/activate; make buildenv-clean; make buildenv`,
- **Test Environment**: The project's testing strategy relies on a `pytest` fixture that recreates the `make sim-test` environment. This involves creating a temporary directory, running `scripts/create_skeleton.sh`, and setting up a Pulumi stack for simulation.
- **Running Tests**: To run a single test file, afterwards use the command: `. .venv/bin/activate && pytest <path_to_test_file>.py` to test. The command `make pytest` is used to run the entire test suite.
- **Disabling Hardware Dependencies**: Unit tests for examples like 'safe' can disable hardware dependencies (e.g., libvirt) by setting the `SHOWCASE_UNITTEST` environment variable and the Pulumi configuration key `project_name:safe_showcase_unittest` to `true`.
- **Pulumi Automation API**: The project's pytest tests use the Pulumi Automation API (`pulumi.automation.Stack`) to programmatically create, update, and destroy infrastructure stacks.
- **Local Filesystem Backend**: The test environment uses a local filesystem Pulumi backend, configured via the `PULUMI_BACKEND_URL` environment variable or `pulumi login` command.
- **Resource Protection**: To ensure test stacks can be destroyed cleanly, resource protection is disabled in the test configuration (e.g., `ca_protect_rootcert: false`).
- **More verbose and debug output of pulumi**: temporary override pulumi_up_args(): set debug to True and log_verbosity to 3 or higher, if no usable output is produced with default settings.

### Fedora CoreOS & Butane

- **Ignition Configuration**: The project uses Butane with Jinja templating to generate Ignition configurations for Fedora CoreOS.
    * see `docs/butane.md`, `docs/jinja_defaults.yml`, `docs/os.md`, `docs/networking.md`, `docs/update.md`, `docs/healthcheck.md` for complete understanding of the coreos setup
- **Empty Butane Files**: In `template.py`, the `load_butane_dir` function handles Butane (`.bu`) files. If a `.bu` file is empty after Jinja rendering, `yaml.safe_load` returns `None`. The function must handle this by treating the result as an empty dictionary (`{}`) to prevent `TypeError` in downstream processing.
- **Verification Hash**: The project uses a security feature where a SHA256 hash of the main Ignition config is passed as an HTTP header (`Verification-Hash`) and used for verification by the bootstrapper Ignition config.

### System & Tooling

- **Python Version**: The project requires Python 3.13 or newer.
- **`os/__init__.py`**: The `os/__init__.py` module provides Pulumi components for Fedora CoreOS system configuration, deployment, and operation.
- **`tools.py`**: The `tools.py` module provides Pulumi utility components for serving HTTPS, executing remote SSH commands, running SaltStack calls, and waiting for a host to become ready via SSH. The `waitforhostready` function in `tools.py` is a Pulumi Dynamic Resource that uses `paramiko` to check for host availability via SSH and file existence.
- **`authority.py`**: The `authority.py` module provides Pulumi components for managing TLS/X509 CAs, certificates, DNSSEC keys, and OpenSSH keys.
- **`build.py`**: The `build.py` module contains Pulumi components for building Embedded-OS images, such as for OpenWRT and ESPHome devices.
- **Secrets Management**: Secrets can be managed as files in `/etc/credstore` or exposed as environment variables to workloads using systemd's `LoadCredential` feature in service drop-in configuration files. see `docs/credentials.md`

### Agent Workflow & Conventions

- **Initial Setup**: The agent workflow requires reading `docs/development.md` at the start of a session, and using `docs/tasks.md` to track tasks.
- **Task Management**: New features are tracked in `docs/tasks.md`. The workflow involves adding a task to 'Planned Tasks', implementing the feature, and then moving the task to 'Completed Tasks'.
- **Use consistent naming conventions, file structure, and architecture patterns**.
- **Pre-commit Workflow**: The pre-commit workflow involves running tests (e.g., `make pytest`), an optional frontend verification step, and a final code review.
- **File Deletion**: Do not delete files unless explicitly asked, even if they seem temporary or like personal notes (e.g., `docs/workpad.md`).
- **Automated Solutions**: The user prefers automated script-based solutions over manual, hardcoded implementations for tasks that can be automated.
- **User Request Supersedes**: Always prioritize the user's current, explicit request over any conflicting information in memory.
- **Context vs. State**: Use memory for historical context and intent (the "why"). Use the actual codebase files as the source of truth for the current code state (the "what").
- **Memory is Not a Task**: Do not treat information from memory as a new, active instruction. Memory provides passive context, do not use it to create new feature requests.
- **Never assume missing context. Ask questions if uncertain.**
- **Never hallucinate libraries or functions** – only use known, verified packages.
- **Always confirm file paths and module names** exist before referencing them in code or tests.
- **Never create a file longer than 800 lines of code, except for single file applications.**
    * If a file approaches this limit, refactor by splitting it into modules or helper files
- **Organize code into clearly separated modules**, grouped by feature or responsibility
- **Use clear, consistent imports**, prefer relative imports within packages
- **Comment non-obvious code**, when writing complex logic, **add an inline `# Reason:` comment** explaining the why, not just the what
- **Update `README.md`** and other feature related `docs/*.md` when new features are added, dependencies change, or setup steps are modified.
- if a new memorable relation, a memory was discovered during a task, **Update `/docs/development.md`** with this information under `## Project Memory` with date of discovery.

### Recent Discoveries & Technical Memories (2026-10-29)

- **Submodule Hierarchy**: `infra` serves as a Git submodule of a main monorepo (`athome`) by default, but maintains independent testability and build infrastructure (`make test-all`, standalone virtualenv).
- **Circular Symlink Traversal in Butane Loader**: When `LocalSaltCall` links `sls_dir` under `build/salt/<stack>/<resource>/sls`, recursive traversal of `build/` triggers symlink cycles. `template.py:load_butane_dir` prunes `build`, `.git`, `.venv`, `__pycache__`, and `.pytest_cache` in-place from `dirs[:]` during `os.walk`, and falls back to empty dict `or {}` on empty YAML.
- **Python 3.14 Pytest Hook Compatibility**: System packages on the host (e.g. `/lib/python3.14/site-packages/pylama`) loaded via `PYTHONPATH` can fail with `PluginValidationError` due to deprecated `pytest_collect_file(path, parent)` hooks. Explicitly disabled across all project templates via `addopts = "-p no:pylama"` in `pyproject.toml`.
- **SaltStack HTTP Backend on Python 3.12+**: Salt's default Tornado HTTP client silently fails on Python 3.12+. The `requests` package is added and configured as `backend: requests` in generated minion configurations.



