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

