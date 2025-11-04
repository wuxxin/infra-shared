# Workpad

Read `docs/agent-workflow.md`, `docs/development.md` and `README.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.
Read and Update `docs/tasks.md` under Section "Planned Tasks" with the detailed description of that tasks.
Then, do each of the described tasks one by one, and update `docs/tasks.md` accordingly.

Required changes:


feat: Add pytest for safe example

Adds a new pytest in `tests/test_safe.py` that creates a test case by
copying `examples/safe` into `target/safe`.

The test replicates the `make sim-test` environment by creating a
temporary directory, running `scripts/create_skeleton.sh`, and setting
up a Pulumi stack for simulation. The `SHOWCASE_UNITTEST` environment
variable is set to `true` to disable hardware-dependent components.

A pytest fixture is included to handle the setup and teardown of the test
environment, ens
