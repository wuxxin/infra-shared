## Safe - Fedora-CoreOS on ARM

- Minimum Viable Function
    - encrypted storage at rest
    - unattended update/boot
        - unattended clevis luks storage unlock via tangd (and tpm2 on libvirt sim)
    - lan available ssl secured postgresql database available for storing data

- Hardware: Raspberry Pi4
    - sdcard with boot and luks encrypted root
    - 2 x usb sticks: luks encrypted raid1 mirrored /var

- Single Container Example
    - postgresql - with mandatory ssl and optional clientcert auth

- Compose Example
    - hello-compose

- Nspawn Example
    - hello-nspawn

- Simulation
    - a libvirt machine with the corresponding features and volumes

