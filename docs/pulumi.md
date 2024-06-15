# Pulumi Resources

- `authority.py` - TLS Certificate-Authority, functions for TLS Certificates and SSH-Provision
- [`os/__init__.py`](os.md) - Operating System Services for Fedora CoreOS and other OS
    - Configuration and Update of Operating System using
        - Butane templating to Ignition for Configuration of system
        - Butane to Saltstack for Update of system
    - DNS Server, HTTPS Frontend, Credentials support
    - Deployment of Container, Compose and NSpawn Images
- `tools.py` - SSH copy/deploy/execute functions, local and remote Salt-Call
- `build.py` - build Embedded-OS Images and IOT Images
    - Openwrt Linux - Network Device Distribution for Router and other network devices
    - Raspberry Extras - U-Boot and UEFI Bios Files for Rpi3 and Rpi4
