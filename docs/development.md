# Development

## Files and Directories Layout

### Development Documents

- `docs/development.md`: (This file) The project file layout, architectural overview, developer and agent guidelines for working with project
- `docs/marimo-development.md`: if present, Developer Guidelines for working with marimo notebooks of this project
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

## Building

- the root `README.md` describes the `examples/skeleton/Makefile` usage, not the root Makefile usage

- `Makefile`: the root central make file for building and developing
- `make help` to list functions
- `mkdocs.yml`: mkdocs configuration
- `pyproject.toml`: python dependencies for pulumi, saltstack, esphome, mkdocs

- make help output: `make help`

| command | description |
| --- | --- |
| buildenv |  Build python environment |
| buildenv-clean |  Remove build environment artifacts |
| clean |  Remove all artifacts |
| docs |  Build docs for local usage |
| docs-clean |  Remove all generated docs |
| docs-online-build |  Build docs for http serve |
| docs-serve |  Rebuild and serve docs with autoreload |
| provision-container |  Build dependencies for provisioning using a container |
| provision-local |  Build dependencies for provisioning using system apps |
| py-clean |  Remove python related artifacts |
| pytest |  Run Tests using "pytest $(args)" |
| pytest-clean |  Remove pytest Artifacts |
| sim__ |  Run "pulumi $(args)" |
| test-all |  Run all tests using local build deps |
| test-all-container |  Run all tests using container build deps |

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

- **Use uv** (the virtual environment and package manager) whenever executing Python commands, including for unit tests.
- **Use `pyproject.toml`** to add or modify dependencies installed during a task execution. as long as there is no version controlled uv.lock, dont add one to the repository.
- **Use python_dotenv and load_env()** for environment variables.
- **Use `pydantic` for data validation**.
- **Use `pytest` for testing**, `playwright` with headless chromium and `pytest-playwright` for gui testing.
- **Use `FastAPI` for APIs**.
- **Use `FastHTML` for HTML**.
- **Use `SQLAlchemy` or `SQLModel` for ORM**.
- **Before adding a new library, look in `pyproject.yaml`** if there is already a fitting library to use.
- **Follow PEP8**, use type hints, and format with `black` or equivalent.
- Write **docstrings for every function** using the Google style:

  ```python
  def example():
      """
      Brief summary

      Args:
          param1 (type): Description
      Returns:
          type: Description
      """
  ```

### Python Testing & Reliability

- **Always create unit tests for new features** (functions, classes, routes, etc).
- **After updating any logic**, check whether existing unit tests need to be updated and update it.
- **Tests should live in a `/tests` folder** mirroring the main app structure.
    - Include at least:
        - 1 test for expected use
        - 1 edge case
        - 1 failure case

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

- **Test Environment**: The project's testing strategy relies on a `pytest` fixture that recreates the `make sim-test` environment. This involves creating a temporary directory, running `scripts/create_skeleton.sh`, and setting up a Pulumi stack for simulation.
- **Running Tests**: To run a single test file, create the build env at first with `. .venv/bin/activate && make buildenv`, afterwards use the command: `. .venv/bin/activate && pytest <path_to_test_file>.py` to test. The command `make pytest` is used to run the entire test suite.
- **Disabling Hardware Dependencies**: Unit tests for examples like 'safe' can disable hardware dependencies (e.g., libvirt) by setting the `SHOWCASE_UNITTEST` environment variable and the Pulumi configuration key `project_name:safe_showcase_unittest` to `true`.
- **Pulumi Automation API**: The project's pytest tests use the Pulumi Automation API (`pulumi.automation.Stack`) to programmatically create, update, and destroy infrastructure stacks.
- **Local Filesystem Backend**: The test environment uses a local filesystem Pulumi backend, configured via the `PULUMI_BACKEND_URL` environment variable or `pulumi login` command.
- **Resource Protection**: To ensure test stacks can be destroyed cleanly, resource protection is disabled in the test configuration (e.g., `ca_protect_rootcert: false`).


### Fedora CoreOS & Butane

- **Ignition Configuration**: The project uses Butane with Jinja templating to generate Ignition configurations for Fedora CoreOS.
    * see `docs/butane.md`, `docs/jinja_defaults.yml`, `docs/os.md`, `docs/networking.md`, `docs/update.md`, `docs/healthcheck.md` for complete understanding of the coreos setup
- **Empty Butane Files**: In `template.py`, the `load_butane_dir` function handles Butane (`.bu`) files. If a `.bu` file is empty after Jinja rendering, `yaml.safe_load` returns `None`. The function must handle this by treating the result as an empty dictionary (`{}`) to prevent `TypeError` in downstream processing.
- **Verification Hash**: The project uses a security feature where a SHA256 hash of the main Ignition config is passed as an HTTP header (`Verification-Hash`) and used for verification by the bootstrapper Ignition config.

### System & Tooling

- **Python Version**: The project requires Python 3.11 or newer.
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



