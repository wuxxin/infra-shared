# Reconfigure OS

reconfigure a remote System by executing salt-call on a butane to saltstack translated config.

- Modifications to `*.bu` and their **referenced files** will result in a new config
- only the butane sections: `storage:{directories,files,links,trees}` and `systemd:unit[:dropins]` are translated

Update Execution:

1. provision: Copies systemd service and a main.sls in combination self sufficent files to the remote target
1. target: overwrite original update service, reload systemd, start update service
1. service: build update container, configure saltstack
1. service: execute salt-call of main.sls in saltstack container with mounts /etc, /var, /run from host
1. salt-call: do a mock-call first, where no changes are made, but will exit with error and stop update if call fails
1. salt-call: reconfigure of storage:{directories,files,links,trees} systemd:unit[:dropins]
1. salt-call: additional migration code written in basedir/*.sls
    - use for adding saltstack migration code to cleanup after updates, eg. deleting files and services
1. salt-call: service_enabled.list, sevice_disabled.list, service_masked.list, service_changed.list are created
1. service: systemctl daemon-reload, enable `service_enabled.list` and disable  `service_disabled.list` services
1. service: systemctl reset-failed, restart services listed in `service_changed.list`
1. service: delete main.sls and var/cache|log because of secrets and as flag that update is done


advantages of this approach:

- it can **update from a broken version of itself**
- calling a systemd service instead of calling a plain shell script for update
    - life cycle managment, independent of the calling shell, doesn't die on disconnect, has logs

the update service detects the following as changes to a service:

- systemd service `instance.(service|path|...)`
- systemd service dropin `instance.service.d/*.conf`
- local, containers and compose environment named `instance*.env`
- container file and support files named `instance.*`
- any containers build files
- any compose build files
