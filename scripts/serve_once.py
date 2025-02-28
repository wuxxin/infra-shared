#!/usr/bin/env python
"""serve a HTTPS path once, use STDIN for config and payload, STDOUT for request_body
  will wait until timeout in seconds is reached, where it will exit 1
  will exit 0 after one successful request

can be used
  as one-time secure data serve for eg. ignition data
  as a webhook on demand where the POST data is sent to STDOUT

calling usage: <yaml-from-STDIN> | $0 [--verbose] --yes | [<request_body-to-STDOUT>]

notes:
- if key or cert is None, a temporary self-signed cert will be created
- if mtls is true, ca_cert must be set, and a mandatory client certificate is needed to connect
- if mtls_clientid is not None, the client certificate CN name needs to match mtls_clientid
- invalid request paths, invalid request methods, invalid or missing client certificates
    return a request error but do not cause the exit of the program.
    only a successful transmission or a timeout will end execution.
"""

import argparse
import copy
import datetime
import http.server
import os
import select
import shutil
import ssl
import sys
import tempfile
import threading
from typing import Any

import yaml

DEFAULT_CONFIG_STR = """
request_ip:
request_path: "/"
request_method: "GET"
request_body_stdout: false
serve_ip: 0.0.0.0
serve_port: 0
hostname: localhost
timeout: 30
cert:
key:
ca_cert:
mtls: false
mtls_clientid:
header:
  "Content-Type": application/json
payload: |
  true
"""
DEFAULT_CONFIG = yaml.safe_load(DEFAULT_CONFIG_STR)

verbose = False


def verbose_print(message: str) -> None:
    """Prints a message to stderr if the global verbose flag is set."""
    if verbose:
        print(message, file=sys.stderr)


def write_file_bytes(filepath: str, content: bytes) -> None:
    """Writes bytes to a file."""
    with open(filepath, "wb") as f:
        f.write(content.encode())


def merge_dicts(dict1: dict, dict2: dict) -> dict:
    """Recursively merges two dictionaries, with dict2 overriding dict1 if a key exists in both."""
    merged = copy.deepcopy(dict1)
    for key, value in dict2.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def generate_self_signed_certificate(hostname: str) -> dict[str, bytes]:
    """Generates a self-signed certificate for the given hostname."""
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
        )
        .not_valid_after(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    return {
        "key": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        "cert": certificate.public_bytes(serialization.Encoding.PEM),
    }


class RequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests, serving a single response based on configuration."""

    config: dict[str, Any] = {}  # Class-level variable to store configuration
    success: bool = False

    def verbose_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        """Sends an error response and optionally logs it."""
        self.send_error(code, message, explain)
        verbose_print(f"{code}: {message}")

    def log_message(self, format: str, *args: Any) -> None:
        """Logs a message if verbose mode is enabled."""
        if verbose:
            super().log_message(format, *args)

    def get_client_cert_common_name(self) -> str | None:
        """Retrieves the Common Name from the client certificate, if available."""
        cert = self.connection.getpeercert()
        if cert and "subject" in cert:
            subject = dict(x[0] for x in cert["subject"])
            return subject.get("commonName")
        return None

    def handle_request(self) -> None:
        """Handles a single HTTP request based on the provided configuration."""
        if self.config["mtls"] and self.config["mtls_clientid"]:
            client_cert_cn = self.get_client_cert_common_name()
            if client_cert_cn != self.config["mtls_clientid"]:
                self.verbose_error(
                    401, f"Invalid Client certificate CN: {client_cert_cn}"
                )
                return

        if (
            self.config["request_ip"]
            and self.client_address[0] != self.config["request_ip"]
        ):
            self.verbose_error(403, f"Invalid Client IP : {self.client_address[0]}")
            return

        if self.command != self.config["request_method"]:
            self.verbose_error(405, f"Invalid request method: {self.command}")
            return

        if self.path != self.config["request_path"]:
            self.verbose_error(404, f"Invalid request path: {self.path}")
            return

        if self.config["request_body_stdout"]:
            content_length = int(self.headers.get("Content-Length", 0))
            request_body = self.rfile.read(content_length).decode("utf-8")
            print(request_body)

        self.send_response(200)
        for key, value in self.config["header"].items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(self.config["payload"].encode("utf-8"))

        # Signal successful response
        type(self).success = True

    def do_GET(self) -> None:
        """Handles GET requests."""
        self.handle_request()

    def do_POST(self) -> None:
        """Handles POST requests."""
        self.handle_request()

    def do_PUT(self) -> None:
        """Handles PUT requests."""
        self.handle_request()


def serve_once(config: dict[str, Any]) -> http.server.HTTPServer:
    """Serves a single HTTPS request or times out."""
    RequestHandler.config = config
    RequestHandler.success = False

    temp_dir = None
    cert_thread = None
    key_thread = None
    httpd = None

    try:
        temp_dir = tempfile.mkdtemp(dir=os.path.join("/run/user", str(os.getuid())))
        cert_fifo_path = os.path.join(temp_dir, "cert.fifo")
        key_fifo_path = os.path.join(temp_dir, "key.fifo")
        os.mkfifo(cert_fifo_path)
        os.mkfifo(key_fifo_path)

        cert_thread = threading.Thread(
            target=write_file_bytes, args=(cert_fifo_path, config["cert"])
        )
        key_thread = threading.Thread(
            target=write_file_bytes, args=(key_fifo_path, config["key"])
        )
        cert_thread.start()
        key_thread.start()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_fifo_path, keyfile=key_fifo_path)

        if config["ca_cert"]:
            context.load_verify_locations(cadata=config["ca_cert"])
            if config["mtls"]:
                context.verify_mode = ssl.CERT_REQUIRED

        verbose_print(f"waiting for request on request_path: {config['request_path']}")
        httpd = http.server.HTTPServer(
            (config["serve_ip"], int(config["serve_port"])),
            RequestHandler,
            bind_and_activate=False,
        )
        httpd.timeout = config["timeout"]
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

        httpd.server_bind()
        httpd.server_activate()

        while not RequestHandler.success:
            # only loop while not successful to allow return
            r, _, _ = select.select([httpd.socket], [], [], httpd.timeout)
            if r:
                httpd.handle_request()
                if RequestHandler.success:
                    break
            else:
                verbose_print("Timeout reached")
                sys.exit(1)

    finally:
        if cert_thread:
            cert_thread.join()
        if key_thread:
            key_thread.join()
        if temp_dir:
            shutil.rmtree(temp_dir)

    # return the httpd instance to allow shutdown and get address
    return httpd


def main() -> None:
    """Parses arguments, loads configuration, and starts the server."""
    global verbose

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Log and Warnings to stderr"
    )
    parser.add_argument("--yes", action="store_true", help="Confirm execution")

    args = parser.parse_args()
    verbose = args.verbose

    if not args.yes:
        print("Error: --yes flag is required to confirm execution")
        sys.exit(1)

    stdin_str = sys.stdin.read()
    loaded_config = yaml.safe_load(stdin_str) if stdin_str.strip() else {}

    config = merge_dicts(DEFAULT_CONFIG, loaded_config)

    if not config["cert"] or not config["key"]:
        verbose_print(
            "Warning: no cert or key set, creating temporary self-signed certificate"
        )
        cert_key_dict = generate_self_signed_certificate(config["hostname"])
        config["cert"] = cert_key_dict["cert"]
        config["key"] = cert_key_dict["key"]

    verbose_print(f"Starting server on port {config['serve_port']}")
    serve_once(config)
    # server will exit after first request or timeout


if __name__ == "__main__":
    main()
