# Workpad

Read `docs/agent-workflow.md`, `docs/development.md` and `README.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.
Read and Update `docs/tasks.md` under Section "Planned Tasks" with the detailed description of that tasks.
Then, do each of the described tasks one by one, and update `docs/tasks.md` accordingly.

Required changes:

refactor tools.py:

- f: ssh_put

        files: {remotepath: localpath,}

- f: ssh_get
        files: {remotepath: localpath,}

- f: ssh_deploy
        files: {remotepath: data,}

make all remotepath, localpath, and data be either string or pulumi output object.
make a pytest case for str and pulumi output.

- **Refactor `tools.py`**
  - Ensure `remotepath`, `localpath`, and `data` can be either a `str` or a `pulumi.Output`.
  - Modify `ssh_put` to accept `files` as a dictionary of `{remotepath: localpath}`.
  - Modify `ssh_get` to accept `files` as a dictionary of `{remotepath: localpath}`.
  - Modify `ssh_deploy` to accept `files` as a dictionary of `{remotepath: data}`.

