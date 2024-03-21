## Safe - Fedora-CoreOS on ARM

- Hardware: Raspberry Pi4

- Storage:
    - encrypted storage at rest
    - sdcard with boot and luks encrypted root
    - 2 x usb sticks: luks encrypted raid1 mirrored /var
    - unattended clevis luks storage unlock for boot via tangd (and tpm2 on libvirt sim)

- Simulation
    - a libvirt machine with the corresponding features and volumes,
        but on amd64 instead of arch64, 8gb boot, 2 x 8gb usb sticks

- Single Container
    - lan available postgresql with mandatory ssl and optional clientcert auth
        - container/postgesql.[conf|container|volume]
        - Containerfile/postgresql

- Compose Showcase Example
    - simple go application returning some ascii fishes
        - compose.bu
        - compose/hello-compose/compose.yml
        - compose/hello-compose/backend/Containerfile
        - compose/hello-compose/backend/main.go

- Nspawn Showcase Example
    - hello-nspawn
        - nspawn.bu
        - nspawn/hello-nspawn/nspawn.provision.sh

