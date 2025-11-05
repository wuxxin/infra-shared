# Tasks

## Planned Tasks

- **feat: Add pytest for safe example**
  Adds a new pytest in `tests/test_safe.py` that creates a test case by
  copying `examples/safe` into `target/safe`.

  The test replicates the `make sim-test` environment by creating a
  temporary directory, running `scripts/create_skeleton.sh`, and setting
  up a Pulumi stack for simulation. The `SHOWCASE_UNITTEST` environment
  variable is set to `true` to disable hardware-dependent components.

  A pytest fixture is included to handle the setup and teardown of the test
  environment, ensuring a clean state for each test run.

## Completed Tasks

- **docs: Update `docs/development.md` with project memories**
  - Gathers all recorded project memories.
  - Organizes them into logical sections.
  - Appends the organized memories to `docs/development.md`.

## Discovered Tasks

## Memory