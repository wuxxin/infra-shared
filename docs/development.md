# Project Development Documentation

## Files and Directories Layout

### Development Documents

- `docs/development.md`: (This file) The project file layout, architectural overview and developer guidelines for working with project.
- `docs/agent-workflow.md`: Development process and coding conventions for software agents.
- `docs/marimo-development.md`: Developer Guidelines for working with marimo notebooks of this project.
- `docs/tasks.md`: A living document tracking tasks of types already completed, newly discovered, to be done, and tracking memories about discovered relations.

### User Documentation

- `README.md`: A user centric view on howto use the project
- `docs/`:  mkdocs documentatio
- see `docs/scripts.md` and `docs/pulumi.md` for scripts and tools
- see `docs/os.md` and `docs/update.md` for coreos system and system update
- see `docs/butane.md` for scripts and tools
- see `docs/scripts.md` for scripts and tools

### Building

- the root `README.md` describes the `examples/skeleton/Makefile` usage, not the root Makefile usage

- `Makefile`: the root central make file for building and developing
- `make help` to list functions
- `mkdocs.yml`: mkdocs configuration
- `pyproject.toml`: python dependencies for pulumi, saltstack, esphome, mkdocs

- make help output:

```txt
buildenv            Build python environment
buildenv-clean      Remove build environment artifacts
clean                Remove all artifacts
docs                 Build docs for local usage and open in browser
docs-clean           Remove all generated docs
docs-online-build    Build docs for http serve
docs-serve           Rebuild and serve docs with autoreload
provision-container  Build dependencies for provisioning using a container
provision-local      Build dependencies for provisioning using system apps
py-clean             Remove python related artifacts
sim__                Run "pulumi $(args)"
test-all-container   Run all tests using container build deps
test-all-local       Run all tests using local build deps
test-scripts         Run script Tests
test-sim             Run sim up Tests
test-sim-clean       Remove Application Artifacts
try-renovate         Run Renovate in dry-run mode
```

## Python Style, Conventions and preferred libraries

- **Use uv** (the virtual environment and package manager) whenever executing Python commands, including for unit tests.
- **Use `pyproject.toml`** to add or modify dependencies installed during a task execution. as long as there is no version controlled uv.lock, dont add one to the repository.
- **Use python_dotenv and load_env()** for environment variables.
- **Use `pydantic` for data validation**.
- **Use `pytest` for testing**, `playwright` and `pytest-playwright` for gui testing.
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
