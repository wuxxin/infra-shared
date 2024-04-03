# Safe - Fedora-CoreOS on Raspberry Pi Appliance

Showcase: a self-updating encrypted storage appliance,

with container, compose and nspawn example in < 600 lines, < 1500 words easy to read code

- Hardware: Raspberry Pi4 (arm64)

- Python Configuration: [_\_init__.py](__init__.py)

- Storage: [storage.bu](storage.bu)
    - encrypted storage at rest
    - sdcard with boot and luks encrypted root
    - 2 x usb sticks: luks encrypted raid1 mirrored /var
    - unattended clevis luks storage unlock for boot via tangd (and tpm2 on libvirt sim)


- Simulation
    - a libvirt machine with the corresponding features and volumes,
        but on amd64 instead of arch64, 8gb boot, 2 x 8gb usb sticks

- Single Container Showcase `Postgresql Server`

    lan available postgresql with mandatory ssl and optional clientcert auth

    - [container.bu](container.bu)
    - [container/postgresql.conf](container/postgresql.conf)
    - [container/postgresql.container](container/postgresql.container)
    - [container/postgresql.volume](container/postgresql.volume)
    - [Containerfile/postgresql/Containerfile](Containerfile/postgresql/Containerfile)

- Compose Showcase Example `hello-compose`

    simple compose file for building and running a go application returning some ascii fishes

    - [compose.bu](compose.bu)
    - [compose/hello-compose/compose.yml](compose/hello-compose/compose.yml)
    - [compose/hello-compose/backend/Containerfile](compose/hello-compose/backend/Containerfile)
    - [compose/hello-compose/backend/main.go](compose/hello-compose/backend/main.go)

- Nspawn Showcase Example `hello-nspawn`

    debian based machine serving a static file using nginx returning some ascii fishes

    - [nspawn.bu](nspawn.bu)
    - [nspawn/hello-nspawn/nspawn.provision.sh](nspawn/hello-nspawn/nspawn.provision.sh)

