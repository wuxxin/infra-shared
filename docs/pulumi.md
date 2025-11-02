# Pulumi Resources

Pulumi components and functions available in this project:

## `os` - CoreOS System Config, Deployment, Operation, Update

This module provides components for managing CoreOS systems.

### Components

-   `ButaneTranspiler`: Translates Jinja-templated Butane files to Ignition and SaltStack Salt format
-   `WaitForHostReady`: Waits for a host to be ready
-   `SystemConfigUpdate`: Updates the system configuration of a host
-   `FcosImageDownloader`: Downloads a Fedora CoreOS image
-   `LibvirtIgniteFcos`: Creates a libvirt VM from an Ignition config
-   `TangFingerprint`: Gets the fingerprint of a Tang server
-   `RemoteDownloadIgnitionConfig`: Creates an Ignition config that downloads the final Ignition config from a URL

### Functions

-   `get_locale`: Gets the locale configuration
-   `butane_clevis_to_json_clevis`: Converts a Butane clevis config to a JSON clevis config

### Usage

```python
from infra.os import ButaneTranspiler, LibvirtIgniteFcos

# translate butane into ignition and saltstack
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, host_environment
)

# create libvirt machine simulation
host_machine = LibvirtIgniteFcos(
    shortname,
    public_config.result,
    volumes=identifiers["storage"],
    memory=4096,
)
```

## `authority` - Authority - TLS/X509 CA and Certificates, DNSSEC Keys, OpenSSH Keys

This module provides components for managing TLS/X509 CAs and certificates, DNSSEC keys, and OpenSSH keys.

### Components

-   `CACertFactoryVault`: Creates a Certificate Authority using HashiCorp Vault
-   `CACertFactoryPulumi`: Creates a Certificate Authority using the Pulumi TLS provider
-   `CASignedCert`: Creates a certificate signed by a CA
-   `SelfSignedCert`: Creates a self-signed certificate
-   `PKCS12Bundle`: Creates a PKCS12 bundle from a key and certificate chain
-   `NSFactory`: Creates DNSSEC keys and trust anchors
-   `TSIGKey`: Creates a TSIG key
-   `SSHFactory`: Creates SSH keys and authorized_keys files

### Functions

-   `create_host_cert`: Creates a host certificate
-   `create_client_cert`: Creates a client certificate
-   `create_selfsigned_cert`: Creates a self-signed certificate
-   `create_sub_ca`: Creates a sub-CA
-   `pem_to_pkcs12_base64`: Converts a PEM certificate and key to a base64-encoded PKCS12 bundle

### Configuration

The `authority.py` module is configured through the `Pulumi.<stack>.yaml` file. The following configuration values are available:

-   `ca_name`, `ca_org`, `ca_unit`, `ca_locality`, `ca_country`, `ca_max_path_length`, `ca_create_using_vault`
-   `ca_validity_period_hours`, `cert_validity_period_hours`
-   `ca_permitted_domains`, `ca_dns_names`
-   `ca_provision_name`, `ca_provision_unit`, `ca_provision_dns_names`
-   `ca_alt_provision_name`, `ca_alt_provision_unit`, `ca_alt_provision_dns_names`
-   `ca_extra_cert_bundle`
-   `ns_extra_ksk_bundle`
-   `ssh_provision_name`

### Usage

```python
from infra.authority import create_host_cert

# create tls host certificate
tls = create_host_cert(hostname, hostname, dns_names)
```


## `tools` - Serve HTTPS, SSH-put/get/execute, Salt-Call, write Removable-Media, other tools

This module provides various tools for use with Pulumi.

### Components

-   `ServePrepare`: Prepares a web resource for serving
-   `ServeOnce`: Serves a web resource once
-   `LocalSaltCall`: Executes a SaltStack salt-call on the local machine
-   `RemoteSaltCall`: Executes a SaltStack salt-call on a remote machine
-   `TimedResource`: A resource that is re-created after a certain amount of time

### Functions

-   `serve_simple`: Serves a simple web resource
-   `ssh_put`: Puts a file on a remote machine
-   `ssh_deploy`: Deploys a file to a remote machine
-   `ssh_execute`: Executes a command on a remote machine
-   `ssh_get`: Gets a file from a remote machine
-   `write_removable`: Writes an image to a removable storage device
-   `encrypted_local_export`: Exports a secret to a local file
-   `public_local_export`: Exports a public value to a local file
-   `log_warn`: Logs a warning message
-   `salt_config`: Generates a SaltStack salt config
-   `get_ip_from_ifname`: Gets the IP address of a network interface
-   `get_default_host_ip`: Gets the default host IP address
-   `get_default_gateway_ip`: Gets the default gateway IP address
-   `sha256sum_file`: Calculates the sha256sum of a file
-   `yaml_loads`: Loads a YAML string

### Usage

```python
from infra.tools import ServePrepare, ServeOnce

# configure the later used remote url for remote controlled setup with encrypted config
serve_config = ServePrepare(
    shortname, serve_interface="virbr0" if stack_name.endswith("sim") else ""
)

# serve secret part of ignition config via ServeOnce
serve_data = ServeOnce(
    shortname,
    config=serve_config.config,
    payload=host_config.result,
    opts=pulumi.ResourceOptions(ignore_changes=["stdin"]),
)
```

## `build.py` - build OS- and IoT-Images

This module provides components for building OpenWRT Linux, Raspberry PI Extras, ESPHOME ESP32 Sensor/Actor Devices Images.

### Components

-   `ESPhomeBuild`: Builds an ESPhome firmware image

### Functions

-   `build_this_salt`: Builds an image or OS using SaltStack
-   `build_raspberry_extras`: Builds Raspberry Pi extra files
-   `build_openwrt`: Builds an OpenWRT image
-   `build_esphome`: Builds an ESPhome firmware image

### Example

```python
from infra.build import build_raspberry_extras

# download bios and other extras for Raspberry PI for customization
extras = build_raspberry_extras()
```
