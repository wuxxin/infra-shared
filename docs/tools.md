### Tools

- `authority.py` - TLS Certificate-Authority, functions for TLS Certificates and SSH-Provision
- `tools.py` - SSH copy/deploy/execute functions, local and remote Salt-Call
- `build.py` - build Embedded-OS Images and IOT Images
    - Openwrt Linux - Network Device Distribution for Router and other network devices
    - Raspberry Extras - U-Boot and UEFI Bios Files for Rpi3 and Rpi4
- `serve_once.py` - serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
- `write_removeable.py` - write image to removable storage specified by serial_number
- `port_forward.py` - request a port forwarding so that serve-port is reachable on public-port
- `from_git.sh` - clone and update from a git repository with ssh, gpg keys and known_hosts from STDIN
