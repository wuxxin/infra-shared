"""
## Pulumi - Authority - TLS/X509 Certificates, OpenSSH Keys, DNSSEC Keys

### Config Values
- ca_name, ca_org, ca_unit, ca_locality, ca_country, ca_max_path_length, ca_create_using_vault
- ca_validity_period_hours, cert_validity_period_hours
- ca_permitted_domains, ca_dns_names,
- ca_provision_name, ca_provision_unit, ca_provision_dns_names
- ca_alt_provision_name, ca_alt_provision_unit, ca_alt_provision_dns_names
- ca_extra_cert_bundle
- ssh_provision_name

### useful resources
- config, stack_name, project_name, this_dir, project_dir
- ca_config
    - ca_name, ca_org, ca_unit, ca_locality, ca_country, ca_max_path_length
    - ca_validity_period_hours, cert_validity_period_hours
    - ca_permitted_domains, ca_permitted_domains_list, ca_dns_names, ca_dns_names_list
    - ca_provision_name, ca_provision_unit, ca_provision_dns_names, ca_provision_dns_names_list
    - ca_alt_provision_name, ca_alt_provision_unit, ca_alt_provision_dns_names, ca_alt_provision_dns_names_list
- ca_factory
    - ca_type, root_key_pem, root_cert_pem, root_bundle_pem
    - provision_key_pem, provision_request_pem, provision_cert_pem
    - alt_provision_key_pem, alt_provision_request_pem, alt_provision_cert_pem
- ssh_provision_name
- ssh_factory
    - provision_key, provision_publickey, authorized_keys
- dns_factory
    - ksk_key, ksk_anchor, transfer_key, acme_update_key, update_key, notify_key

### Functions
- create_host_cert
- create_client_cert
- create_selfsigned_cert
- create_sub_ca
- pem_to_pkcs12_base64

### Components
- SSHFactory
- CACertFactoryVault
- CACertFactoryPulumi
- CASignedCert
- SelfSignedCert
- TSIGKey
- DNSFactory

"""

import os
import json
import copy
import base64
import re

import pulumi
import pulumi_tls as tls
import pulumi_random as random
import pulumi_command as command
from pulumi_command.local import Logging as LocalLogging
from pulumi import Output, Alias, ResourceOptions

from cryptography import x509
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    load_pem_private_key,
    pkcs12,
)

from .tools import (
    yaml_loads,
    public_local_export,
    get_default_host_ip,
    get_ip_from_ifname,
)


config = pulumi.Config("")
stack_name = pulumi.get_stack()
project_name = pulumi.get_project()
this_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(this_dir, ".."))

# https://superuser.com/questions/1492207/
# XXX use validity period specified by apple (custom CA issued: <825, Public CA: <398)
default_hours_ca = 24 * 365 * 8
default_hours_public_cert = 24 * 397
default_hours_private_cert = 24 * 824
default_early_renewal_hours = 48


def pem_to_pkcs12_base64(
    pem_cert: str, pem_key: str, password: str, friendlyname: str = ""
) -> str:
    """Converts a TLS client certificate and its associated private key in PEM format
    into a password-protected PKCS#12 file, encoded as a base64 string

    :param pem_cert: The TLS client certificate in PEM format as a string
    :param pem_key: The private key in PEM format as a string
    :param password: The password to protect the PKCS#12 archive
    :return: Base64 encoded string of the PKCS#12 archive, formatted with line breaks
    """
    # Load the certificate from PEM
    cert = x509.load_pem_x509_certificate(pem_cert.encode("utf-8"))
    # Load the private key from PEM
    key = load_pem_private_key(pem_key.encode("utf-8"), password=None)
    # Create a PKCS#12 blob
    p12_data = pkcs12.serialize_key_and_certificates(
        friendlyname.encode("utf-8"),
        key,
        cert,
        None,
        BestAvailableEncryption(password.encode("utf-8")),
    )
    # Base64 encode the binary PKCS#12 data
    base64_data = base64.encodebytes(p12_data).decode("utf-8")
    # Format the base64 data (e.g., multiline string)
    formatted_base64_data = "".join([f"{line}\n" for line in base64_data.splitlines()])
    return formatted_base64_data


class PKCS12Bundle(pulumi.ComponentResource):
    def __init__(self, name, key_pem, cert_chain_pem, password, opts=None):
        super().__init__("pkg:index:PKCS12Bundle", name, None, opts)

        self.result = pulumi.Output.all(
            key_pem=key_pem,
            cert_chain_pem=cert_chain_pem,
            password=password,
        ).apply(
            lambda args: pem_to_pkcs12_base64(
                pem_cert=str(args["cert_chain_pem"]),
                pem_key=str(args["key_pem"]),
                password=str(args["password"]),
                friendlyname=name,  # Use resource name as friendlyname
            )
        )
        self.register_outputs({"result": self.result})


class SSHFactory(pulumi.ComponentResource):
    def __init__(self, name, ssh_provision_name, opts=None):
        super().__init__("pkg:index:SSHFactory", name, None, opts)

        ssh_provision_key = tls.PrivateKey(
            "ssh_provision_key",
            algorithm="ED25519",
            opts=pulumi.ResourceOptions(parent=self),
        )
        ssh_provision_publickey = ssh_provision_key.public_key_openssh.apply(
            lambda x: "{} {}".format(x.strip(), ssh_provision_name)
        )
        # read ssh_authorized_keys from project_dir/authorized_keys
        ssh_authorized_keys = open(
            os.path.join(project_dir, "authorized_keys"), "r"
        ).readlines()
        # combine with provision key
        ssh_authorized_keys += [Output.concat(ssh_provision_publickey, "\n")]
        ssh_authorized_keys = Output.concat(*ssh_authorized_keys)

        self.provision_key = ssh_provision_key
        self.provision_publickey = ssh_provision_publickey
        self.authorized_keys = ssh_authorized_keys
        self.register_outputs({})


class TSIGKey(pulumi.ComponentResource):
    def __init__(self, name, opts=None):
        def extract_secret(data):
            try:
                return data["key"][0]["secret"]
            except (KeyError, IndexError) as e:
                raise Exception(f"Failed to find TSIG secret in YAML: {e}") from e

        super().__init__("pkg:index:TSIGKey", name, None, opts)
        this_opts = ResourceOptions.merge(
            ResourceOptions(parent=self, additional_secret_outputs=["stdout"]), opts
        )
        tsig_key_command = command.local.Command(
            "{}_tsig_key".format(name),
            create=f"keymgr -t {name} hmac-sha256",
            dir=this_dir,
            logging=LocalLogging.NONE,
            opts=this_opts,
        )
        parsed_yaml = yaml_loads(tsig_key_command.stdout)
        self.secret = pulumi.Output.secret(parsed_yaml.apply(extract_secret))
        self.register_outputs({})


class DNSFactory(pulumi.ComponentResource):
    def __init__(self, name, names_list=None, opts=None):
        "names_list: list of strings taken as domains for anchorcert instead of name"
        super().__init__("pkg:index:DNSFactory", name, None, opts)
        this_opts = ResourceOptions.merge(ResourceOptions(parent=self), opts)
        dns_root = command.local.Command(
            "{}_dns_root".format(name),
            create=f"scripts/dnssec_gen.sh --zone {name}",
            dir=this_dir,
            logging=LocalLogging.NONE,
            opts=ResourceOptions.merge(
                ResourceOptions(additional_secret_outputs=["stdout"]), this_opts
            ),
        )
        dns_secrets = pulumi.Output.json_loads(dns_root.stdout)
        self.ksk_key = Output.secret(dns_secrets["ksk_key"])

        # make anchor file contain all requested domains
        base_anchor_key = Output.unsecret(dns_secrets["ksk_anchor"])
        all_anchor_outputs = []
        if names_list:
            for anchor_domain in names_list:
                transformed_anchor = base_anchor_key.apply(
                    lambda cert_text, domain=anchor_domain: re.sub(
                        "^[^.]+\\.", f"{domain}.", cert_text, flags=re.M
                    )
                )
                all_anchor_outputs.append(transformed_anchor)
        else:
            all_anchor_outputs.append(base_anchor_key)
        self.ksk_anchor = Output.all(*all_anchor_outputs).apply(
            lambda anchors: "\n".join(anchors)
        )

        self.transfer_key = TSIGKey(f"transfer-{name}", this_opts)
        self.update_key = TSIGKey(f"update-{name}", this_opts)
        self.acme_update_key = TSIGKey(f"acme-update-{name}", this_opts)
        self.notify_key = TSIGKey(f"notify-{name}", this_opts)
        self.register_outputs({})


class CACertFactoryVault(pulumi.ComponentResource):
    def __init__(self, name, ca_config, opts=None):
        super().__init__("pkg:index:CACertFactoryVault", name, None, opts)

        # asure that permitted_domains is set to empty list and empty string, if not configured
        vault_config = copy.deepcopy(ca_config)
        if vault_config.get("ca_permitted_domains", None) is None:
            vault_config.update({"ca_permitted_domains_list": [], "ca_permitted_domains": ""})

        vault_ca = command.local.Command(
            "{}_vault_ca".format(name),
            create="scripts/vault_pipe.sh --yes",
            stdin=json.dumps(vault_config),
            dir=this_dir,
            logging=LocalLogging.NONE,
            opts=pulumi.ResourceOptions(
                parent=self,
                additional_secret_outputs=["stdout"],
                # XXX protect CA Cert because it will always be an error to delete it
                protect=True,
                # XXX ignore changes to input of CA creation, because it can not be changed
                ignore_changes=["stdin"],
                # XXX make pulumi find legacy name for ca_factory_fault_ca
                aliases=[Alias(name="vault_ca")] if name == "ca_factory" else [],
            ),
        )
        # XXX use json_loads to workaround https://github.com/pulumi/pulumi-command/issues/166
        ca_secrets = pulumi.Output.json_loads(vault_ca.stdout)
        ca_root_hash = command.local.Command(
            "{}_root_hash".format(name),
            create="openssl x509 -hash -noout",
            stdin=Output.unsecret(ca_secrets["ca_root_cert_pem"]),
            logging=LocalLogging.NONE,
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[vault_ca],
                # XXX make pulumi find legacy name for ca_factory_root_hash
                aliases=[Alias(name="ca_root_hash")] if name == "ca_factory" else [],
            ),
        )

        self.ca_type = "vault"
        self.root_key_pem = Output.secret(ca_secrets["ca_root_key_pem"])
        self.root_cert_pem = Output.unsecret(ca_secrets["ca_root_cert_pem"])
        self.root_hash_id = ca_root_hash.stdout
        self.root_bundle_pem = Output.concat(
            self.root_cert_pem, "\n", vault_config.get("ca_extra_cert_bundle", "\n")
        )
        self.provision_key_pem = Output.secret(ca_secrets["ca_provision_key_pem"])
        self.provision_request_pem = Output.unsecret(ca_secrets["ca_provision_request_pem"])
        self.provision_cert_pem = Output.unsecret(ca_secrets["ca_provision_cert_pem"])
        self.alt_provision_key_pem = Output.secret(ca_secrets["ca_alt_provision_key_pem"])
        self.alt_provision_request_pem = Output.unsecret(
            ca_secrets["ca_alt_provision_request_pem"]
        )
        self.alt_provision_cert_pem = Output.unsecret(ca_secrets["ca_alt_provision_cert_pem"])
        self.register_outputs({})


class CACertFactoryPulumi(pulumi.ComponentResource):
    def __init__(self, name, ca_config, opts=None):
        super().__init__("pkg:index:CACertFactoryPulumi", name, None, opts)

        if ca_config.get("ca_max_path_length", None) is not None:
            raise ValueError("'ca_max_path_length' is unsupported. use CACertFactoryVault")

        # create root key, root cert
        # XXX protect CA Cert because it will always be an error to delete it
        # XXX mtls requirements for eg. inside google cloud
        #       https://cloud.google.com/load-balancing/docs/mtls#certificate-requirements
        # XXX vault ignores everything except CRL,CertSign,DigitalSignature,
        #       in root and intermediates, citing a CAB Forum requirement as reason.
        #       https://developer.hashicorp.com/vault/api-docs/secret/pki#key_usage-2
        ca_uses = ["cert_signing", "crl_signing", "digital_signature"]
        ca_root_key = tls.PrivateKey(
            "{}_root_key".format(name),
            algorithm="ECDSA",
            ecdsa_curve="P384",
            opts=pulumi.ResourceOptions(parent=self, protect=True),
        )
        ca_root_cert = tls.SelfSignedCert(
            "{}_root_cert".format(name),
            allowed_uses=ca_uses,
            private_key_pem=ca_root_key.private_key_pem,
            is_ca_certificate=True,
            validity_period_hours=ca_config["ca_validity_period_hours"],
            dns_names=ca_config["ca_dns_names_list"],
            subject=tls.SelfSignedCertSubjectArgs(
                common_name=ca_config["ca_name"],
                organizational_unit=ca_config["ca_unit"],
                organization=ca_config["ca_org"],
                country=ca_config["ca_country"],
                locality=ca_config["ca_locality"],
            ),
            opts=pulumi.ResourceOptions(parent=self, protect=True),
        )

        # create provision and alt provision key
        ca_provision_key = tls.PrivateKey(
            "{}_provision_key".format(name),
            algorithm="ECDSA",
            ecdsa_curve="P384",
            opts=pulumi.ResourceOptions(parent=self),
        )
        ca_alt_provision_key = tls.PrivateKey(
            "{}_alt_provision_key".format(name),
            algorithm="ECDSA",
            ecdsa_curve="P384",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # create provision and alt provision cert request
        ca_provision_request = tls.CertRequest(
            "{}_prov_request".format(name),
            private_key_pem=ca_provision_key.private_key_pem,
            dns_names=ca_config["ca_provision_dns_names_list"],
            subject=tls.CertRequestSubjectArgs(
                common_name=ca_config["ca_provision_name"],
                organizational_unit=ca_config["ca_provision_unit"],
                organization=ca_config["ca_org"],
                country=ca_config["ca_country"],
                locality=ca_config["ca_locality"],
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )
        ca_alt_provision_request = tls.CertRequest(
            "{}_alt_prov_request".format(name),
            private_key_pem=ca_alt_provision_key.private_key_pem,
            dns_names=ca_config["ca_alt_provision_dns_names_list"],
            subject=tls.CertRequestSubjectArgs(
                common_name=ca_config["ca_alt_provision_name"],
                organizational_unit=ca_config["ca_alt_provision_unit"],
                organization=ca_config["ca_org"],
                country=ca_config["ca_country"],
                locality=ca_config["ca_locality"],
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # create provision and alt provision cert
        # substract one day from validity_period_hours of root ca for [alt] provision ca
        ca_provision_cert = tls.LocallySignedCert(
            "{}_provision_cert".format(name),
            allowed_uses=ca_uses,
            ca_cert_pem=ca_root_cert.cert_pem,
            ca_private_key_pem=ca_root_key.private_key_pem,
            cert_request_pem=ca_provision_request.cert_request_pem,
            validity_period_hours=(ca_config["ca_validity_period_hours"] - 24),
            is_ca_certificate=True,
            opts=pulumi.ResourceOptions(parent=self),
        )
        ca_alt_provision_cert = tls.LocallySignedCert(
            "{}_alt_provision_cert".format(name),
            allowed_uses=ca_uses,
            ca_cert_pem=ca_root_cert.cert_pem,
            ca_private_key_pem=ca_root_key.private_key_pem,
            cert_request_pem=ca_alt_provision_request.cert_request_pem,
            validity_period_hours=(ca_config["ca_validity_period_hours"] - 24),
            is_ca_certificate=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # hash ca_root cert, needed for symlinking and therelike
        ca_root_hash = command.local.Command(
            "{}_root_hash".format(name),
            create="openssl x509 -hash -noout",
            stdin=ca_root_cert.cert_pem,
            logging=LocalLogging.NONE,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.ca_type = "pulumi"
        self.root_key_pem = ca_root_key.private_key_pem
        self.root_cert_pem = ca_root_cert.cert_pem
        self.root_hash_id = ca_root_hash.stdout
        self.root_bundle_pem = Output.concat(
            self.root_cert_pem, "\n", ca_config.get("ca_extra_cert_bundle", "\n")
        )
        self.provision_key_pem = ca_provision_key.private_key_pem
        self.provision_request_pem = ca_provision_request.cert_request_pem
        self.provision_cert_pem = ca_provision_cert.cert_pem
        self.alt_provision_key_pem = ca_alt_provision_key.private_key_pem
        self.alt_provision_request_pem = ca_alt_provision_request.cert_request_pem
        self.alt_provision_cert_pem = ca_alt_provision_cert.cert_pem
        self.register_outputs({})


class CASignedCert(pulumi.ComponentResource):
    """Pulumi Component Resource representing a certificate signed by a Certificate Authority (CA)
    Returns:
    - key: tls.PrivateKey of the certificate
    - request: tls.CertRequest certificate request that was used to generate the signed certificate
    - cert: tls.LocallySignedCert resource representing the signed certificate itself
    - chain: Pulumi Output object that concatenates the signed certificate with the certificate chain
    if "client_auth" in allowed_uses:
    - pkcs12_bundle: Pulumi Output object of base64 encoded transport password secured pkcs12 client certificate file data
    - pkcs12_password: Pulumi Output object of random password generator
    """

    def __init__(self, name, cert_config, opts=None):
        def undef_or_none_def(struct, entry, default):
            return struct.get(entry) if struct.get(entry) is not None else default

        super().__init__("pkg:index:CASignedCert", "{}_cacert".format(name), None, opts)

        ca_config = cert_config["ca_config"]
        ca_factory = cert_config["ca_factory"]
        common_name = cert_config["common_name"]
        dns_names = cert_config["dns_names"]
        ip_addresses = cert_config.get("ip_addresses", [])
        allowed_uses = cert_config["allowed_uses"]
        is_ca_certificate = cert_config.get("is_ca_certificate", False)
        organizational_unit = cert_config.get("organizational_unit", None)
        use_provision_ca = undef_or_none_def(cert_config, "use_provision_ca", True)
        custom_provision_ca = cert_config.get("custom_provision_ca", None)
        validity_period_hours = ca_config.get(
            "cert_validity_period_hours", default_hours_private_cert
        )
        early_renewal_hours = ca_config.get(
            "cert_early_renewal_hours", default_early_renewal_hours
        )

        # decide which CA to use, root-ca, provision ca or custom sub ca
        if use_provision_ca:
            if custom_provision_ca is None:
                ca_cert_pem = ca_factory.provision_cert_pem
                ca_private_key_pem = ca_factory.provision_key_pem
                resource_chain = ca_factory.provision_cert_pem
            else:
                ca_cert_pem = custom_provision_ca.cert.cert_pem
                ca_private_key_pem = custom_provision_ca.key.private_key_pem
                resource_chain = custom_provision_ca.chain
        else:
            ca_cert_pem = ca_factory.root_cert_pem
            ca_private_key_pem = ca_factory.root_key_pem
            resource_chain = ""

        resource_subject = tls.CertRequestSubjectArgs(
            common_name=common_name,
            organization=ca_config["ca_org"],
            organizational_unit=organizational_unit,
        )
        resource_key = tls.PrivateKey(
            "{}_cert_key".format(name),
            algorithm="ECDSA",
            ecdsa_curve="P256",
            opts=pulumi.ResourceOptions(parent=self),
        )

        resource_request = tls.CertRequest(
            "{}_cert_request".format(name),
            private_key_pem=resource_key.private_key_pem,
            dns_names=dns_names,
            ip_addresses=ip_addresses,
            subject=resource_subject,
            opts=pulumi.ResourceOptions(parent=self),
        )
        resource_cert = tls.LocallySignedCert(
            "{}_cert".format(name),
            allowed_uses=allowed_uses,
            is_ca_certificate=is_ca_certificate,
            ca_cert_pem=ca_cert_pem,
            ca_private_key_pem=ca_private_key_pem,
            cert_request_pem=resource_request.cert_request_pem,
            early_renewal_hours=early_renewal_hours,
            validity_period_hours=validity_period_hours,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.key = resource_key
        self.request = resource_request
        self.cert = resource_cert
        self.chain = Output.concat(resource_cert.cert_pem, "\n", resource_chain)

        if "client_auth" in allowed_uses and "server_auth" not in allowed_uses:
            # Create a password encrypted PKCS#12 object if only client_auth
            # Use the certificate's PEM and key PEM as keepers.
            # If the cert or key changes, a new password will be generated.
            password_keepers = {
                "cert_pem": self.cert.cert_pem,
                "key_pem": self.key.private_key_pem,
            }
            self.pkcs12_password = random.RandomPassword(
                "{}_pkcs12_password".format(name),
                length=24,
                special=False,
                keepers=password_keepers,
                opts=pulumi.ResourceOptions(parent=self),
            )
            self.pkcs12_bundle = PKCS12Bundle(
                name=f"{name}_pkcs12_bundle",
                key_pem=self.key.private_key_pem,
                cert_chain_pem=self.chain,
                password=self.pkcs12_password.result,
                opts=pulumi.ResourceOptions(parent=self),
            )

        self.register_outputs({})


class SelfSignedCert(pulumi.ComponentResource):
    def __init__(self, name, cert_config, opts=None):
        super().__init__("pkg:index:SelfSignedCert", "{}_sscert".format(name), None, opts)

        common_name = cert_config["common_name"]
        dns_names = cert_config["dns_names"]
        ip_addresses = cert_config.get("ip_addresses", [])
        org_name = cert_config["org_name"]
        allowed_uses = cert_config["allowed_uses"]
        validity_period_hours = cert_config.get(
            "cert_validity_period_hours", default_hours_private_cert
        )
        early_renewal_hours = cert_config.get(
            "cert_early_renewal_hours", default_early_renewal_hours
        )

        resource_key = tls.PrivateKey(
            "{}_selfsigned_key".format(name),
            algorithm="ECDSA",
            ecdsa_curve="P256",
            opts=pulumi.ResourceOptions(parent=self),
        )
        resource_cert = tls.SelfSignedCert(
            "{}_selfsigned_cert".format(name),
            private_key_pem=resource_key.private_key_pem,
            allowed_uses=allowed_uses,
            dns_names=dns_names,
            ip_addresses=ip_addresses,
            is_ca_certificate=False,
            subject=tls.SelfSignedCertSubjectArgs(
                common_name=common_name,
                organization=org_name,
            ),
            early_renewal_hours=early_renewal_hours,
            validity_period_hours=validity_period_hours,
            opts=pulumi.ResourceOptions(parent=self),
        )
        # hash cert, needed for symlinking and therelike
        resource_hash = command.local.Command(
            "{}_selfsigned_hash".format(name),
            create="openssl x509 -hash -noout",
            stdin=resource_cert.cert_pem,
            logging=LocalLogging.NONE,
            opts=pulumi.ResourceOptions(parent=self),
        )
        self.key = resource_key
        self.cert = resource_cert
        self.hash_id = resource_hash.stdout
        self.register_outputs({})


def create_sub_ca(
    resource_name,
    common_name,
    dns_names,
    custom_ca_config=None,
    custom_ca_factory=None,
    organizational_unit=None,
    validity_period_hours=None,
    allowed_uses=["cert_signing", "crl_signing", "digital_signature"],
    use_provision_ca=None,
    custom_provision_ca=None,
    opts=None,
):
    if not custom_ca_config:
        custom_ca_config = ca_config
    if not custom_ca_factory:
        custom_ca_factory = ca_factory
    if not validity_period_hours:
        validity_period_hours = custom_ca_config["ca_validity_period_hours"] - 24
    if custom_provision_ca:
        use_provision_ca = True

    provision_ca_config = {
        "ca_config": custom_ca_config,
        "ca_factory": custom_ca_factory,
        "common_name": common_name,
        "dns_names": dns_names,
        "is_ca_certificate": True,
        "organizational_unit": organizational_unit,
        "validity_period_hours": validity_period_hours,
        "allowed_uses": allowed_uses,
        "use_provision_ca": use_provision_ca,
        "custom_provision_ca": custom_provision_ca,
    }
    provision_ca_cert = CASignedCert(resource_name, provision_ca_config, opts=opts)
    return provision_ca_cert


def create_host_cert(
    resource_name,
    common_name,
    dns_names,
    ip_addresses=[],
    custom_ca_config=None,
    custom_ca_factory=None,
    use_provision_ca=None,
    custom_provision_ca=None,
    opts=None,
):
    """Creates a host certificate for the given common name and DNS names.

    Args:
    - resource_name (str): Pulumi resource name
    - common_name (str): Certificate common name
    - dns_names (list of str): DNS names for the certificate
    - ip_addresses (list of str): IP addresses for the certificate
    - custom_ca_config (dict): Custom CA configuration parameters
    - custom_ca_factory (dict): Custom CA factory parameters
    - use_provision_ca (bool): Whether to use the provision CA
    - custom_provision_ca (dict): Custom provision CA parameters
    - opts (pulumi.ResourceOptions): Pulumi resource options
    Returns:
    - CASignedCert: A `CASignedCert` object representing the created host certificate
    """
    host_config = {
        "ca_config": ca_config if not custom_ca_config else custom_ca_config,
        "ca_factory": ca_factory if not custom_ca_factory else custom_ca_factory,
        "common_name": common_name,
        "dns_names": dns_names,
        "ip_addresses": ip_addresses,
        "allowed_uses": ["client_auth", "server_auth"],
        "use_provision_ca": use_provision_ca,
        "custom_provision_ca": custom_provision_ca,
    }
    host_cert = CASignedCert(resource_name, host_config, opts=opts)
    return host_cert


def create_client_cert(
    resource_name,
    common_name,
    dns_names=[],
    custom_ca_config=None,
    custom_ca_factory=None,
    use_provision_ca=None,
    custom_provision_ca=None,
    opts=None,
):
    """Creates a client certificate for the given common name and DNS names

    Args:
    - resource_name (str): pulumi resource name
    - common_name (str): certificate common name
    - dns_names (list of str): DNS names for the certificate
    - custom_ca_config (dict): custom CA configuration parameters
    - custom_ca_factory (dict): custom CA factory parameters
    - use_provision_ca (bool): whether to use the provision CA
    - custom_provision_ca (dict): custom provision CA parameters
    Returns:
    - a `CASignedCert` object representing the created client certificate
    """
    client_config = {
        "ca_config": ca_config if not custom_ca_config else custom_ca_config,
        "ca_factory": ca_factory if not custom_ca_factory else custom_ca_factory,
        "common_name": common_name,
        "dns_names": dns_names,
        "allowed_uses": ["client_auth"],
        "use_provision_ca": use_provision_ca,
        "custom_provision_ca": custom_provision_ca,
    }
    client_cert = CASignedCert(resource_name, client_config, opts=opts)
    return client_cert


def create_selfsigned_cert(
    resource_name,
    common_name,
    dns_names=[],
    ip_addresses=[],
    org_name="",
    allowed_uses=["client_auth", "server_auth"],
    opts=None,
):
    """Creates a self-signed certificate for the given common name and DNS names

    Args:
    - resource_name (str): Pulumi resource name
    - common_name (str): Certificate common name
    - dns_names (list of str): DNS names for the certificate
    - ip_addresses (list of str): IP addresses for the certificate
    - org_name (str): Organization name for the certificate. Defaults to common_name
    - allowed_uses (list of str): Allowed uses for the certificate.
        Defaults to ['client_auth', 'server_auth']
    - opts (pulumi.ResourceOptions): Pulumi resource options. Defaults to None.
    Returns:
    - SelfSignedCert object
    """
    self_config = {
        "common_name": common_name,
        "dns_names": dns_names,
        "ip_addresses": ip_addresses,
        "org_name": org_name if org_name else common_name,
        "allowed_uses": allowed_uses,
    }
    selfsigned_cert = SelfSignedCert(resource_name, self_config, opts=opts)
    return selfsigned_cert


# ### X509 ca_config
__ca_permitted_list = config.get_object(
    "ca_permitted_domains",
    ["lan", project_name],
)
__ca_dns_list = config.get_object(
    "ca_dns_names",
    ["ca.{}.lan".format(project_name), "ca.{}.{}".format(project_name, project_name)],
)
__prov_dns_list = config.get_object("ca_provision_dns_names", __ca_dns_list)
__alt_prov_dns_list = config.get_object("ca_alt_provision_dns_names", __ca_dns_list)

ca_config = {
    "ca_name": config.get("ca_name", "{}-{}-Root-CA".format(project_name, stack_name)),
    "ca_org": config.get("ca_org", "{}-{}".format(project_name, stack_name)),
    "ca_unit": config.get("ca_unit", "Certificate Authority"),
    "ca_locality": config.get("ca_locality", "World"),
    "ca_country": config.get("ca_country", "UN"),
    "ca_validity_period_hours": config.get_int("ca_validity_period_hours", default_hours_ca),
    "cert_validity_period_hours": config.get_int(
        "cert_validity_period_hours", default_hours_private_cert
    ),
    "ca_extra_cert_bundle": config.get("ca_extra_cert_bundle", "\n"),
    "ca_permitted_domains": ",".join(__ca_permitted_list),
    "ca_permitted_domains_list": __ca_permitted_list,
    "ca_dns_names": ",".join(__ca_dns_list),
    "ca_dns_names_list": __ca_dns_list,
    "ca_provision_name": config.get(
        "ca_provision_name", "{}-{}-Provision-CA".format(project_name, stack_name)
    ),
    "ca_provision_unit": config.get("ca_provision_unit", "Certificate Provision"),
    "ca_provision_dns_names": ",".join(__prov_dns_list),
    "ca_provision_dns_names_list": __prov_dns_list,
    "ca_alt_provision_name": config.get(
        "ca_alt_provision_name",
        "{}-{}-Alternate-Provision-CA".format(project_name, stack_name),
    ),
    "ca_alt_provision_unit": config.get(
        "ca_alt_provision_unit", "Alternate Certificate Provision"
    ),
    "ca_alt_provision_dns_names": ",".join(__alt_prov_dns_list),
    "ca_alt_provision_dns_names_list": __alt_prov_dns_list,
}
pulumi.export("ca_config", ca_config)


# ### X509 Certificate Authority
if config.get_bool("ca_create_using_vault", True):
    # use vault for initial CA creation and permitted_domains support
    ca_factory = CACertFactoryVault("ca_factory", ca_config)
else:
    # create cert and keys using buildin pulumi tls module
    ca_factory = CACertFactoryPulumi("ca_factory", ca_config)
pulumi.export("ca_factory", ca_factory)

# write out public part of ca cert for usage as file
exported_ca_cert = public_local_export("ca_factory", "ca_cert.pem", ca_factory.root_cert_pem)
# write out public bundle of ca certs for usage as file
exported_ca_bundle = public_local_export(
    "ca_factory", "ca_bundle.pem", ca_factory.root_bundle_pem
)


# sub ca for optional acme provider
acme_sub_ca = create_sub_ca(
    "acme_sub_ca",
    "{}-{}-ACME-Provision-Sub-CA".format(project_name, stack_name),
    dns_names=["acme.{}".format(domain) for domain in ca_config["ca_permitted_domains_list"]],
    use_provision_ca=True,
    organizational_unit="ACME Certificate Provision Unit",
)
pulumi.export("acme_sub_ca", acme_sub_ca)


# provision host cert for use in servce_once.py
provision_host_names = [
    "provision_host.{}".format(domain) for domain in ca_config["ca_permitted_domains_list"]
]
# TODO make provision_host_ip_addresses default more robust, but resourceful
provision_ip_addresses = config.get(
    "provision_host_ip_addresses",
    [str(get_default_host_ip()), "10.87.240.1", "10.87.241.1", "10.88.0.1", "192.168.122.1"],
)
# create a host cert usable for both server_auth and client_auth
provision_host_tls = create_host_cert(
    provision_host_names[0],
    provision_host_names[0],
    provision_host_names,
    ip_addresses=provision_ip_addresses,
)
pulumi.export("provision_host_tls", provision_host_tls)


# ### SSH config
ssh_provision_name = config.get(
    "ssh_provision_name", "provision@{}.{}".format(stack_name, project_name)
)
pulumi.export("ssh_provision_name", ssh_provision_name)

# ### SSH Certificate and authorized_keys
ssh_factory = SSHFactory("ssh_factory", ssh_provision_name)
pulumi.export("ssh_factory", ssh_factory)


# ### DNS config for internal domains using one ksk and anchor
dns_factory = DNSFactory("internal", names_list=["internal", "podman", "nspawn"])
pulumi.export("dns_factory", dns_factory)
