import os
import subprocess
from pulumi.automation import Stack
from .utils import add_pulumi_program
import base64


def test_pkcs12_client_cert(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args):
    program = """
import pulumi
from infra.authority import create_client_cert

# Create a client certificate
librewolf_client_cert = create_client_cert(
    "librewolf.user_host_CLIENT_CERT",
    "librewolf.user@test-host",
    dns_names=["librewolf.user@test-host"],
    opts=pulumi.ResourceOptions(),
)

pulumi.export("pkcs12_bundle_b64", librewolf_client_cert.pkcs12_bundle.result)
pulumi.export("pkcs12_password", librewolf_client_cert.pkcs12_password.result)
"""
    add_pulumi_program(pulumi_project_dir, program)

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    pkcs12_password = up_result.outputs["pkcs12_password"].value
    pkcs12_bundle_b64 = up_result.outputs["pkcs12_bundle_b64"].value
    pkcs12_data = base64.b64decode(pkcs12_bundle_b64.encode("utf-8"))

    # Get all certs from the bundle in PEM format
    cmd_pkcs12 = ["openssl", "pkcs12", "-nokeys", "-passin", f"pass:{pkcs12_password}"]
    pkcs12_proc = subprocess.run(
        cmd_pkcs12, input=pkcs12_data, capture_output=True, check=True
    )

    # Check that we have at least two certificates (client + intermediate)
    certs = pkcs12_proc.stdout.decode("utf-8").strip().split("-----END CERTIFICATE-----")
    certs = [c for c in certs if c.strip()]
    assert len(certs) >= 2

    # Use openssl to parse the PEM output of the first cert (the client cert)
    cmd_x509 = ["openssl", "x509", "-noout", "-subject", "-issuer"]
    x509_proc = subprocess.run(
        cmd_x509,
        input=(certs[0] + "-----END CERTIFICATE-----").encode("utf-8"),
        capture_output=True,
        check=True,
    )

    stdout_str = x509_proc.stdout.decode("utf-8")
    # Check the subject and issuer of the client certificate
    assert "CN=librewolf.user@test-host" in stdout_str
    assert "CN=project-sim-Provision-CA" in stdout_str
