# Workpad

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:


---

Feature: Fix mkdocs_gensrc.py, Extend Documentation from sourcecode information.

- read at `mkdocs.yml`, `Makefile`.

- fix `mkdocs_gensrc.py`, as it does not run under github runner.
even on debug output, i only see "DEBUG   -  Running `files` event from plugin 'gen-files'" , but locally (where it is run with the same "make docs-online-build") it works and includes the example/safe files.

- make mkdocs_gensrc.py realize if it is called from within mkdocs_gensrc, or just as script from outside.
on outside, just displays what pages would be created. be careful with testing mkdocs_gensrc.py, because a simple run of it might create the files in the source dir, and mess up further testing. if unsure test this with `git status` to see additional files.

- make a test case in tests/ (read `tests/conftest.py` in case you need fixtures) to run mkdocs_gensrc.py to just display the would be created markdown files, and test for `src/examples/safe/__init__.py.md` and `src/authority.py.md`

- make another test to run `make docs-online-build` and check for output in expected directory, and there for the inclusion of the two files from the test above, but in the final page output.

`docs/pulumi.md`.
in pulumi the pulumi resources are documented.

From there i want a link to the extracted component (module, class and function docstrings) information build from
from `tools.py`, `authority.py` `os/__init__.py` `build.py` and `template.py` (which is mostly nonpulumi python).
make mkdocs_gensrc.py also include these python files as rendered markdown in src/... and link to them.

use `make buildenv` to create a buildenv, if other commands error.
use `make docs-online-build` to recreate the documentation page.


---

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:

Feature: make the sha256 hash of the compiled butane ignition file that will be transferred to the remote available in the remote download ignition file as header as security token for requesting the real ignition file and as verification hash of the expected file content.


- `os.__init__.py`: add to Butanetranspiler():
  self.ignition_config_hash generated from hash of (self.ignition_config)
  hash (string): the hash of the config, as used in the butane specification, in the form <type>-<value> where type is "sha256" and value is the computed hashvalue

- `tools.ServePrepare`: add argument request_header={} , serve_once.py already handles it.

- `os.__init__.py`: RemoteDownloadIgnitionConfig(... add argument remote_hash="" , rename arg remoteurl to remote_url.

if not empty: remote_hash: add to butane: in the same category of "ignition:config:replace:source" append to replace

```
http_headers:
  "Verification-Hash": remote_hash
verification:
  hash: remote_hash
```

- `examples/safe`:  modify the usage of ServePrepare, RemoteDownloadIgnitionConfig.

add request_header={"Verification-Hash": host_config.ignition_config_hash},
and remote_hash


- implement a test case in tests/test_butane_verification.py:

read tests/conftest.py for fixtures knowledge, read tests/test_tools.py as example pulumi test, do a minimal:
    - create_host_cert
    - host_config = ButaneTranspiler(
    - serve_config = ServePrepare(
    - public_config = RemoteDownloadIgnitionConfig(
    - host_update = SystemConfigUpdate(
    - export all, for testing purpose

and test for Verification Hash in ignition config and header

- use `make pytest args="tests/test_butane_verification.py"` to execute this test, `make pytest` for executing all tests.


---

        # read ssh_authorized_keys from project_dir/authorized_keys and combine with provision key
        self.authorized_keys = ssh_provision_publickey.apply(
            lambda key: "".join(
                open(os.path.join(project_dir, "authorized_keys"), "r").readlines()
                + ["{}\n".format(key)]
            )
        )


