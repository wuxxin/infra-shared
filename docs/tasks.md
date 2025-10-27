# Tasks

Read `docs/agent-workflow.md`, `docs/development.md` and `README.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.
Read and Update `docs/tasks.md` under Section "Planned Tasks" with the detailed description of that tasks.
Then, do each of the described tasks one by one, and update `docs/tasks.md` accordingly.
Required changes:

## Planned Tasks

- Add basis test and fixtures with pytest

  -


test: docs ## Run Tests
	@echo "+++ $@"
	mkdir -p build/tests/output
	. .venv/bin/activate && pytest --screenshot on --video retain-on-failure --output build/tests/output tests/


## Completed Tasks

## Discovered Tasks

## Memory
