## Safe - Fedora-CoreOS on ARM

- Minimum Viable Function
    - encrypted storage at rest
    - unattended boot using clevis luks storage unlock via tangd (and tpm2 on libvirt sim)
    - lan available ssl secured postgresql database available for storing data

- Hardware: Raspberry Pi4
    - sdcard with boot and luks encrypted root
    - 2 x usb sticks: luks encrypted raid1 mirrored /var

- Simulation
    - a libvirt machine with the corresponding features and volumes,
        but on amd64 instead of arch64, 8gb boot, 2x8gb usb sticks

- Single Container Example
    - postgresql - with mandatory ssl and optional clientcert auth
        - container/postgesql.[conf|container|volume]
        - Containerfile/postgresql

- Compose Example
    - simple go application returning some ascii fishes
        - compose.bu
        - compose/hello-compose/compose.yml
        - compose/hello-compose/backend/Containerfile
        - compose/hello-compose/backend/main.go

- Nspawn Example
    - hello-nspawn
        - nspawn.bu
        - nspawn/hello-nspawn/nspawn.provision.sh

