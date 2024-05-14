# Scripts

- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `write_removeable.py` - write image to removable storage specified by serial_number
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN

### CoreOS Administration

- use `toolbox create` and `toolbox enter` to have a fedora container available.
- use `dnf install package` to install packages inside toolbox.
