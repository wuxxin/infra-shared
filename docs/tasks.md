# Tasks

## Planned Tasks

- Add basic test and fixtures with pytest
- use `make pytest` to run pytest
- analyse `Makefile` target `sim-test` and `scripts/create_skeleton.sh` to recreate the sim-test setup and make pytest fixtures for a pytest pulumi stack test that will get different tests added to the stack. the stack is then tested with equivalent of `pulumi up --stack sim` meaning the fixtures will always create , prefill a sim stack.
- first test is a plain import of `authority.py`, and the sucessful result of running pulumi up equivalent.
- in addition to session fixtures there should be a function for easy includes of python into main to be tested as stack, to run a stack with includes you like
- the authority.py test is just a empty setup
- please use pulumi programatically for execution and also for checking expected stack results.
- there should be a function to assert for files in the current state/files/sim dir , for easy access of files output

## Completed Tasks

## Discovered Tasks

## Memory
