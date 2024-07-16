# Safe - Fedora-CoreOS on Raspberry Pi Appliance

## Showcase: a self-updating rolling release encrypted storage appliance

with container, compose and nspawn example in ~ 600 lines, ~ 1500 words code.

- Hardware: Raspberry Pi4 (arm64) 4GB, 1 sdcard, 2 x usb stick
- Python Configuration: [_\_init__.py](__init__.py)
- Storage: [storage.bu](storage.bu)
    - encrypted storage at rest
    - `boot`, luks encrypted `root` on sdcard
    - luks encrypted raid1 mirrored `/var` on usb sticks
    - unattended `clevis` luks storage unlock for boot via tangd (and tpm2 on libvirt sim)
- Simulation
    - a libvirt machine with the corresponding features and volumes
        - 4gb ram, amd64 instead of arch64, 8gb boot, 2 x 8gb usb sticks

### Single Container Showcases

#### `Postgresql Server`

public available `postgresql` server with mandatory ssl and optional clientcert auth

- [container.bu](container.bu)
- [container/postgresql.conf](container/postgresql.conf)
- [container/postgresql.container](container/postgresql.container)
- [container/postgresql.volume](container/postgresql.volume)
- [Containerfile/postgresql/Containerfile](Containerfile/postgresql/Containerfile)

#### `Tang Server`

public available `tang` server MTLS secured with **mandatory clientcert** on https and on port 9443

- [container.bu](container.bu)
- [container/tang.container](container/tang.container)
- [container/tang.volume](container/tang.volume)
- [Containerfile/tang/Containerfile](Containerfile/tang/Containerfile)

### Compose Showcase

#### `hello-compose`

simple `compose` file for building and running a go application returning some ascii fishes

- [compose.bu](compose.bu)
- [compose/hello-compose/compose.yml](compose/hello-compose/compose.yml)
- [compose/hello-compose/backend/Containerfile](compose/hello-compose/backend/Containerfile)
- [compose/hello-compose/backend/main.go](compose/hello-compose/backend/main.go)

### Nspawn Showcase

#### `hello-nspawn`

debian based `nspawn` machine serving a static file using nginx returning some ascii fishes

- [nspawn.bu](nspawn.bu)
- [nspawn/hello-nspawn/nspawn.provision.sh](nspawn/hello-nspawn/nspawn.provision.sh)
