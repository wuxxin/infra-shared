# Safe - Fedora-CoreOS on Raspberry Pi Appliance

## Showcase: a self-updating rolling release encrypted storage appliance

with container, compose and nspawn example in ~ 600 lines, ~ 1500 words code.

- Hardware: Raspberry Pi4 (arm64) 4GB, 1 sdcard, 2 x usb stick
- Python Configuration: [_\_init__.py](__init__.py)
- Storage: [storage.bu](storage.bu)
    - encrypted storage at rest
    - `boot`, luks encrypted `root` on sdcard
    - luks encrypted raid1 mirrored `/var` on usb sticks
    - unattended `clevis` luks storage unlock for boot via tangd and tpm2 (on simulation)
- Simulation
    - a libvirt uefi machine with tpm and the corresponding features and volumes
        - 4gb ram, amd64 instead of arch64, 8gb boot, 2 x 8gb usb sticks

For the simulation environment with libvirt the host system must also have a configured libvirt.

### Single Container Showcases

#### `Postgresql Server`

public available `postgresql` server with mandatory ssl and optional clientcert auth

- [module.bu](postgresql/module.bu)
- [postgresql.conf](postgresql/container/postgresql.conf)
- [postgresql.container](postgresql/container/postgresql.container)
- [postgresql.volume](postgresqlcontainer/postgresql.volume)
- [Containerfile](postgresql/Containerfile/postgresql/Containerfile)

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
