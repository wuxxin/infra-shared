# Development

## Files and Directories Layout

### Development Documents

- `docs/development.md`: (This file) The project file layout, architectural overview and developer guidelines for working with project.
- `docs/agent-workflow.md`: Development process and coding conventions for software agents.
- `docs/marimo-development.md`: Developer Guidelines for working with marimo notebooks of this project.
- `docs/tasks.md`: A living document tracking tasks of types already completed, newly discovered, to be done, and tracking memories about discovered relations.

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

### Development Scripts

all inside directory `scripts`:

- `create_skeleton.sh`
- `dnssec_gen.sh` - Generates DNSSEC KSK private and public key (Anchor Data) and outputs them as JSON
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `provision_shell.sh`
- `requirements.sh`
- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `shell_inside_sim.sh`
- `vault_pipe.sh` - use vault as a commandline input JSON from STDIN, output a root CA and two provision CA as JSON to STDOUT
- `write_removable.py` - write image to removable storage specified by serial_number

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
| pytest |  Run pytest Tests |
| pytest-clean |  Remove pytest Artifacts |
| sim__ |  Run "pulumi $(args)" |
| test-all-container |  Run all tests using container build deps |
| test-all-local |  Run all tests using local build deps |
| test-scripts |  Run script Tests |
| test-sim |  Run sim up Tests |
| test-sim-clean |  Remove Application Artifacts |
| try-renovate |  Run Renovate in dry-run mode |

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
- treat **state as code**, favor **state reconcilation** tools
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

