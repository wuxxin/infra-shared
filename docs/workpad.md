# Workpad

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:

---

        # read ssh_authorized_keys from project_dir/authorized_keys and combine with provision key
        self.authorized_keys = ssh_provision_publickey.apply(
            lambda key: "".join(
                open(os.path.join(project_dir, "authorized_keys"), "r").readlines()
                + ["{}\n".format(key)]
            )
        )
---

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

- use one time `make buildenv` to build env, then `. .venv/bin/activate && pytest tests/test_butane_verification.py` to execute this test, `make pytest` for executing all tests.
