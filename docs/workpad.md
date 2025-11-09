# Workpad

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:


---

- os/__init__.py: systemconfigupdate:

this component transfers the update service and main.sls using config.deployed=ssh_deploy and executes this with config_updated=ssh_execute.

sometimes, ssh_deploy finishes, but ssh_execute fails. i would like that the component realizes that, and will try ssh_deploy and ssh_execute next time again.

---

        # read ssh_authorized_keys from project_dir/authorized_keys and combine with provision key
        self.authorized_keys = ssh_provision_publickey.apply(
            lambda key: "".join(
                open(os.path.join(project_dir, "authorized_keys"), "r").readlines()
                + ["{}\n".format(key)]
            )
        )
