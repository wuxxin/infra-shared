# Workpad

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:

---

write out all recorded memory, group in sections and update `docs/development.md` with the contents.

---


        # read ssh_authorized_keys from project_dir/authorized_keys and combine with provision key
        self.authorized_keys = ssh_provision_publickey.apply(
            lambda key: "".join(
                open(os.path.join(project_dir, "authorized_keys"), "r").readlines()
                + ["{}\n".format(key)]
            )
        )


---

feature: refactor waitforhostready from os.__init__.py to tools.py:

new waitforhostready (function), and WaitForHostReady(component or custom resource): uses only one timeout (default 150 seconds),
use paramiko, look at SSHSftp(pulumi.CustomResource): download_file for pulumi and paramiko ssh setup.
use `/usr/bin/readlink -f` as single command for file_to_exist test.

make new logic that total timeout (adjustable) = 150, try to connect every 5 seconds, if paramiko is able to connect, check for file_to exist,
if not disconnect, wait 5 seconds, then go into try to connect every 5 seconds again (so 10 seconds after connect, file exists and disconnect), if connected and disconnected from the server, wait 5 seconds, loop, if 150 seconds is passed, fail.

implement a test case in tests/test_waitforhostready.py:
read tests/conftest.py for fixtures knowledge, read tests/test_tools.py as example pulumi test.

extend fixtures for test_waitforhostready that creates a paramiko ssh server,
with or without a file ready in a temp directory, and then:

test: start check for ssh connect exist file, but start sshserv after 20sec without file, then:
restart sshserv after 10 sec with file

test: start check set timeout to 3 and dont start sshserv for timeout case.

use one time `make buildenv` to build env, then `. .venv/bin/activate ; pytest tests/test_waitforhostready.py` to execute this test, `make pytest` for executing all tests.

change examples/safe/__init__.py for the new waithostready.

after test_waitforhostready.py passes, execute `make pytest` to see if test_safe still passes too.


---


Feature: make the sha256 hash of the compiled butane ignition file that will be transferred to the remote available in the remote download ignition file as header as security token for requesting the real ignition file and as verification hash of the expected file content.


- `os.__init__.py`: add to Butanetranspiler():
  self.ignition_config_hash generated from hash of (self.ignition_config)
  hash (string): the hash of the config, in the form <type>-<value> where type is "sha256" and value is the computed hashvalue

- `tools.ServePrepare`: add argument request_header={} , serve_once.py already handles it.

- `os.__init__.py`: RemoteDownloadIgnitionConfig(... add argument remote_hash=""

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

::

implement a test case in tests/test_butane_verification.py:
read tests/conftest.py for fixtures knowledge, read tests/test_tools.py as example pulumi test,

do a minimal:
- create_host_cert
- ButaneTranspiler
- ServePrepare
- RemoteDownloadIgnitionConfig
- SystemConfigUpdate

and test for Verification Hash in ignition config and header

use one time `make buildenv` to build env, then `. .venv/bin/activate ; pytest tests/test_butane_verification.py` to execute this test, `make pytest` for executing all tests.
