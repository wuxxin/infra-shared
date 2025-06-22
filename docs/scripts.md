# Scripts

- `create_skeleton.sh`
- `dnssec_gen.sh` - Generates DNSSEC KSK private and public key (Anchor Data) and outputs them as JSON
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `provision_shell.sh`
- `requirements.sh`
- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `shell_inside_sim.sh`
- `vault_pipe.sh`
- `write_removable.py` - write image to removable storage specified by serial_number

## CoreOS Administration

- use `toolbox create` and `toolbox enter` to have a fedora container available.
- use `dnf install package` to install packages inside toolbox.
