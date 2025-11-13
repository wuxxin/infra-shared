# Pulumi Resources

Pulumi components, dynamic resources, and functions available.

## `authority` - TLS/X509 CA & Certs, DNSSEC, OpenSSH

Resources for managing TLS/X509 CAs, certificates, DNSSEC keys, and OpenSSH keys.

### Components

-   `CACertFactory`
    Creates a Certificate Authority using either HashiCorp Vault or the Pulumi TLS provider
-   `CASignedCert`
    Creates a certificate signed by a Certificate Authority (CA)
-   `SelfSignedCert`
    Creates a self-signed certificate
-   `PKCS12Bundle`
    Creates a PKCS12 bundle from a certificate and private key
-   `EncryptedPrivateKey`
    Creates an encrypted private key in PEM format
-   `NSFactory`
    Manages DNSSEC keys and anchors
-   `TSIGKey`
    Generates a TSIG (Transaction Signature) key
-   `SSHFactory`
    Manages SSH keys for provisioning

### Functions

-   `create_host_cert`
    Creates a host certificate with both client and server authentication enabled
-   `create_client_cert`
    Creates a client certificate with only client authentication enabled
-   `create_selfsigned_cert`
    Creates a self-signed certificate
-   `create_sub_ca`
    Creates a subordinate Certificate Authority (CA)

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

### Example

```python
from infra.authority import create_host_cert

# Create a TLS host certificate
tls = create_host_cert(hostname, hostname, dns_names)
```

## `tools` - Serve HTTPS, SSH-put/get/exec, SaltCall, ImgTransfer

This module provides various tools for use with Pulumi.

### Components

-   `ServePrepare`
    Prepares to serve a one-time web resource by generating a dynamic configuration
-   `ServeOnce`
    Serves a one-time, secure web resource and shuts down after the first request
-   `LocalSaltCall`
    Executes a local SaltStack call
-   `RemoteSaltCall`
    Executes a SaltStack call on a remote host
-   `BuildFromSalt`
    Executes a local SaltStack call to build an image or OS

- c: SSHPut
- c: SSHDeploy
- c: SSHGet
- c: SSHExecute

### Dynamic Resources

-   `WaitForHostReady`
    Waits for a remote host to be ready by checking for the existence of a specific file over SSH
-   `TimedResource`
    Regenerates its value after a specified timeout has passed

### Functions

-   `serve_simple`
    Serves a one-time web resource with a simple configuration
-   `ssh_put`
    Copies files from the local machine to a remote host over SSH
-   `ssh_deploy`
    Deploys string data as files to a remote host over SSH
-   `ssh_execute`
    Executes a command on a remote host over SSH
-   `ssh_get`
    Copies files from a remote host to the local machine over SSH

-   `write_removable`
    Writes an image to a removable storage device
-   `encrypted_local_export`
    Exports and encrypts data to a local file using `age`
-   `public_local_export`
    Exports data to a local file without encryption

-   `log_warn`
    Logs a multi-line string to the Pulumi console with line numbers
-   `salt_config`
    Generates a SaltStack minion configuration
-   `get_ip_from_ifname`
    Retrieves the first IPv4 address from a network interface
-   `get_default_host_ip`
    Retrieves the IP address of the default network interface
-   `get_default_gateway_ip`
    Retrieves the IP address of the default gateway
-   `sha256sum_file`
    Calculates the SHA256 checksum of a file
-   `yaml_loads`
    Deserializes a YAML string into a Pulumi output

### Example

#### ServePrepare and ServeOnce

```python
from infra.tools import ServePrepare, ServeOnce

# Prepare the server configuration
serve_config = ServePrepare(
    shortname, serve_interface="virbr0" if stack_name.endswith("sim") else ""
)

# Serve the Ignition config
serve_data = ServeOnce(
    shortname,
    config=serve_config.config,
    payload=host_config.result,
    opts=pulumi.ResourceOptions(ignore_changes=["stdin"]),
)
```

## `os` - CoreOS Config, Deployment, Operation, Update

Resources for managing CoreOS systems.

### Components

-   `ButaneTranspiler`
    Transpiles Jinja2-templated Butane files into Ignition JSON and a SaltStack state
-   `SystemConfigUpdate`
    Updates the configuration of a remote system using a transpiled SaltStack state
-   `FcosImageDownloader`
    Downloads and decompresses a Fedora CoreOS image
-   `LibvirtIgniteFcos`
    Creates a Fedora CoreOS virtual machine with Libvirt
-   `TangFingerprint`
    Retrieves a Tang server's fingerprint
-   `RemoteDownloadIgnitionConfig`
    Creates a minimal Ignition configuration that downloads the full configuration from a remote URL

### Functions

-   `get_locale`
    Retrieves and merges locale settings from default and Pulumi configurations
-   `build_raspberry_extras`
    Builds extra files for Raspberry Pi, such as bootloader firmware
-   `butane_clevis_to_json_clevis`
    Parses a Butane config and extracts Clevis SSS (Shamir's Secret Sharing) configurations for LUKS-encrypted devices

### Example

#### Translate Butane and create a Libvirt Machine from config

```python
from infra.os import ButaneTranspiler, LibvirtIgniteFcos

# Translate Butane into Ignition and SaltStack state
host_config = ButaneTranspiler(
    shortname, hostname, tls, butane_yaml, files_basedir, host_environment
)

# Create a Libvirt virtual machine
host_machine = LibvirtIgniteFcos(
    shortname,
    public_config.result,
    volumes=identifiers["storage"],
    memory=4096,
)
```

#### Build Raspberry Extras

```python
from infra.os import build_raspberry_extras

# Download extra files for Raspberry Pi
extras = build_raspberry_extras()
```
