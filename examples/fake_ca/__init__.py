"""
# Fake-CA Example

Create:

- a Root CA with Max Path Length=3 suitable for accaptance in browsers
- a Provision CA based on Root CA
- a MitM CA based on Provision CA for usage in transparent tls proxies
- an example host cert based on MitM CA

## export

- ca_config
- ca_factory

"""

import pulumi
from infra.authority import (
    CACertFactoryVault,
    create_sub_ca,
    create_host_cert,
    default_hours_ca,
    default_hours_public_cert,
)

__ca_dns_list = ["ca.totally-fine"]
__prov_dns_list = __ca_dns_list

ca_config = {
    "ca_name": "not-at-all-suspicious-Root-CA",
    "ca_org": "Totally-Fine Inc.",
    "ca_unit": "Cyber^2-Security-Unit",
    "ca_locality": "World",
    "ca_country": "UN",
    "ca_validity_period_hours": default_hours_ca,
    "ca_max_path_length": 3,
    "ca_dns_names_list": __ca_dns_list,
    "ca_dns_names": ",".join(__ca_dns_list),
    "ca_provision_name": "not-at-all-Provision-CA",
    "ca_provision_unit": "Very Cyber Provision Unit",
    "ca_provision_dns_names_list": __prov_dns_list,
    "ca_provision_dns_names": ",".join(__prov_dns_list),
    # XXX mimic a public available root-ca chain, validity hours of certs must meet public criteria
    # https://superuser.com/questions/1492207/
    "cert_validity_period_hours": default_hours_public_cert,
}

# use vault, because of ca_max_path_length
ca_factory = CACertFactoryVault("fake_ca_factory", ca_config)
pulumi.export("fake_ca_factory", ca_factory)

# example mitm cert, for usage in transparent tls proxies
mitm_ca = create_sub_ca(
    "fake_ca_mitm_ca",
    "Computer-in-the-middle-CA",
    dns_names=["mitm.totally-fine"],
    custom_ca_config=ca_config,
    custom_ca_factory=ca_factory,
    use_provision_ca=True,
    organizational_unit="Totally fine Sub-Unit",
)
pulumi.export("fake_ca_mitm_ca", mitm_ca)

# example mitm host cert
mitm_host = create_host_cert(
    "fake_mitm_host",
    "fake.google.com",
    dns_names=["fake.google.com"],
    custom_ca_config=ca_config,
    custom_ca_factory=ca_factory,
    custom_provision_ca=mitm_ca,
)
pulumi.export("fake_mitm_host", mitm_host)
