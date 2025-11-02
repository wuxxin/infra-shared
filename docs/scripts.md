# Scripts

Usage of the scripts located in the `scripts/` directory.

## `create_skeleton.sh`

This script creates a new project skeleton with the necessary directories and files. It initializes a new git repository, creates the `docs`, `state`, and `target` directories, and populates the project with a basic `Makefile`, `pyproject.toml`, `README.md`, `__main__.py`, `Pulumi.yaml`, `config-template.yaml`, `.gitignore`, and `mkdocs.yml`.

Usage:

```bash
./scripts/create_skeleton.sh --yes [--project-dir dirname] [--name-library dirname]
```

-   `--yes`: Confirms the execution of the script.
-   `--project-dir dirname`: Specifies the project directory. Defaults to `../../`.
-   `--name-library dirname`: Specifies the name of the shared infrastructure directory. Defaults to `infra`.

## `dnssec_gen.sh`

This script generates DNSSEC KSK private and public keys (Anchor Data) and outputs them to STDOUT as JSON.

Usage:

```bash
./scripts/dnssec_gen.sh --zone name
```

-   `--zone name`: The name of the zone to generate keys for.

## `from_git.sh`

This script is used to clone and update a git repository. It can also be used to bootstrap a new system by creating a new user, installing the necessary packages, and setting up the git repository.

Usage:

**Bootstrap:**

```bash
./scripts/from_git.sh bootstrap --url <giturl> --branch <branch> \
    --user <user> --home <homedir> --git-dir <gitdir> \
    [--export-dir <targetdir>] [--revision-dir <revisiondir>] \
    [--keys-from-stdin | --keys-from-file <filename>]
```

**Pull:**

```bash
./scripts/from_git.sh pull --url <giturl> --branch <branch> \
    --user <user> --git-dir <gitdir> \
    [--export-dir <targetdir>] [--revision-dir <revisiondir>]
```

## `port_forward.py`

This script requests a port forwarding so that a `serve-port` is reachable on a `public-port`.

Usage:

```bash
./scripts/port_forward.py \
    [--yaml-from-stdin] [--serve-port <port>] [--public-port <port>] \
    [--gateway-ip <ip>] [--protocol <protocol>] [--lifetime-sec <seconds>] \
    [--yaml-to-stdout] [--silent] \
    [--get-host-ip] [--get-gateway-ip] [--get-public-ip]
```

## `provision_shell.sh`

This script starts a shell inside the provisioning container.

Usage:

```bash
./scripts/provision_shell.sh [command]
```

-   `command`: The command to run inside the container. Defaults to `/usr/bin/bash`.

## `requirements.sh`

This script checks and installs the necessary packages for the project.

Usage:

```bash
./scripts/requirements.sh
    --install [--dry-run] | \
    --install-extra [--user] [--dry-run] | \
    --check [--verbose] | \
    --list | \
    --containerfile
```

## `salt-call.py`

This script is a wrapper for the `salt-call` command. It includes monkeypatches for Python > 3.10 and > 3.12.

Usage:

This script is intended to be used in the same way as the `salt-call` command.

## `serve_once.py`

This script serves a file once over HTTPS. It uses STDIN for YAML configuration and payload to configure the service.

Usage:

```bash
<yaml-from-STDIN> | \
    ./scripts/serve_once.py [--verbose] --yes | \
    [<request_body-to-STDOUT>]
```

## `shell_inside_sim.sh`

This script starts a shell inside a running libvirt simulation.

Usage:

```bash
./scripts/shell_inside_sim.sh
```

## `vault_pipe.sh`

This script uses vault to create a root CA and two provision CAs. It takes a JSON configuration file from STDIN and outputs a JSON file with the generated certificates and keys to STDOUT.

Usage:

```bash
<json-from-stdin> | ./scripts/vault_pipe.sh --yes | <json-to-stdout>
```

## `write_removable.py`

This script writes an image to a removable storage device. It uses the serial number of the device to identify it.

Usage:

```bash
./scripts/write_removable.py --dest-serial <serial> [--dest-size <size>] \
    --source-image <image> [--patch <source> <dest_on_partition>] \
    [--list] [--verbose | --silent]
```