#!/usr/bin/env python
import argparse
import datetime
import http.server
import os
import select
import shutil
import socket
import socketserver
import ssl
import sys
import tempfile
import threading
import ssl

import yaml


usage_str = """serve a HTTPS path once, using stdin for configuration and payload

will exit 0 after one sucessful request, but continue to wait until timeout 
    in seconds is reached, where it will exit 1.

uses only buildin python packages except yaml, and cryptography if certificate creation is needed.

invalid request paths, invalid request methods, invalid or missing client certificates
    return an request error, but do not cause the exit of the program. 
    only a sucessful transmission or a timeout will end execution.

if key or cert is None, a temporary selfsigned cert will be created
if mtls is true, a ca_cert must be set, and a mandatory client certificate is needed to connect
if mtls_clientid is not None, the correct id of the clientcertificate is needed to connect
"""


def verbose_print(message):
    if args.verbose:
        print(message, file=sys.stderr)


def write_cert(cert_fifo_path, cert):
    with open(cert_fifo_path, "wb") as cert_fifo:
        cert_fifo.write(cert)


def write_key(key_fifo_path, key):
    with open(key_fifo_path, "wb") as key_fifo:
        key_fifo.write(key)


def generate_self_signed_certificate(hostname):
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
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
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


class MyHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        if isinstance(self.connection, socket.socket):
            self.connection = self.wrap_socket(self.connection)

    def verbose_error(self, code: int, message: str | None = None, explain: str | None = None):
        self.send_error(code, message, explain)
        if args.verbose:
            print("{}: {}".format(code, message), file=sys.stderr)

    def wrap_socket(self, sock):
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_sock = ssl_context.wrap_socket(sock, server_side=True)
        return ssl_sock

    def get_client_cert_common_name(self):
        if "subject" in self.connection.getpeercert():
            subject = dict(x[0] for x in self.client_certificate["subject"])
            if "commonName" in subject:
                return subject["commonName"]
        return None

    def handle_command(self):
        """
        - client_address is the client IP address in the form (host, port);
        - command, path and version are the broken-down request line;
        - headers is an instance of email.message.Message (or a derived class) containing the header information;
        - rfile is a file object open for reading positioned at the start of the optional input data part;
        - wfile is a file object open for writing.
        """
        if config["mtls"] and config["mtls_clientid"]:
            client_cert_cn = self.get_client_cert_common_name()
            if client_cert_cn != config["mtls_clientid"]:
                self.verbose_error(401, f"Invalid Client certificate CN: {client_cert_cn}")
                return

        if config["request_ip"] and self.client_address[0] != config["request_ip"]:
            self.verbose_error(403, f"Invalid Client IP : {self.client_address[0]}")
            return

        if self.command != config["request_method"]:
            self.verbose_error(405, f"Invalid request method: {self.command}")
            return

        if self.path != config["request_path"]:
            self.verbose_error(404, f"Invalid request path: {self.path}")
            return

        if config["request_body_to_stdout"]:
            content_length = int(self.headers.get("Content-Length", 0))
            request_body = self.rfile.read(content_length)
            print(request_body.decode("utf-8"))

        self.send_response(200)
        [self.send_header(key, value) for key, value in config["header"].items()]
        self.end_headers()
        self.wfile.write(config["payload"].encode("utf-8"))

    def do_GET(self):
        self.handle_command()

    def do_POST(self):
        self.handle_command()

    def do_PUT(self):
        self.handle_command()


# configure defaults
default_config_str = """
request_ip:
request_path: "/"
request_method: "GET"
request_body_to_stdout: true
serve_ip: 0.0.0.0
serve_port: 8443
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
default_config = yaml.safe_load(default_config_str)
default_short = ", ".join(["{}: {}".format(k, v) for k, v in default_config.items()])

# Parse command line arguments
parser = argparse.ArgumentParser(
    description=usage_str + "\ndefaults:\n{}\n".format(default_short),
    formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument(
    "--verbose", action="store_true", default=False, help="Log warnings to stderr"
)
parser.add_argument("--yes", action="store_true", required=True, help="Confirm execution")

if not sys.argv[1:]:
    # print help and exit if called without parameter
    parser.print_help()
    sys.exit(1)

args = parser.parse_args()
stdin_str = sys.stdin.read()

if not stdin_str.strip():
    verbose_print("Warning: no configuration from stdin, using only defaults!")
    loaded_config = {}
else:
    loaded_config = yaml.safe_load(stdin_str)

# merge YAML config from stdin with defaults
config = {**default_config, **loaded_config}

if not config["cert"] or not config["key"]:
    verbose_print("Warning: no cert or key, creating temporary selfsigned certificate")
    cert_key_dict = generate_self_signed_certificate("localhost")
    config["cert"] = cert_key_dict["cert"]
    config["key"] = cert_key_dict["key"]


try:
    # workaround for load_cert_chain(certfile,keyfile), which only works with "real" files
    # create named pipes for cert and key
    temp_dir = tempfile.mkdtemp(dir=os.path.join("/run/user", str(os.getuid())))
    cert_fifo_path = os.path.join(temp_dir, "cert.fifo")
    key_fifo_path = os.path.join(temp_dir, "key.fifo")
    os.mkfifo(cert_fifo_path)
    os.mkfifo(key_fifo_path)

    # Create and start threads to write to named pipes
    cert_thread = threading.Thread(target=write_cert, args=(cert_fifo_path, config["cert"]))
    key_thread = threading.Thread(target=write_key, args=(key_fifo_path, config["key"]))
    cert_thread.start()
    key_thread.start()

    # Set up SSL context
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile=cert_fifo_path, keyfile=key_fifo_path)
    if config["ca_cert"]:
        ssl_ctx.load_verify_locations(cadata=config["ca_cert"])
        if config["mtls"]:
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    # Set up HTTP context, create HTTPS server
    HandlerClass = MyHTTPRequestHandler
    HandlerClass.protocol_version = "HTTP/1.1"
    HandlerClass.ssl_ctx = ssl_ctx
    httpd = socketserver.TCPServer(
        (config["serve_ip"], config["serve_port"]), HandlerClass, bind_and_activate=False
    )
    httpd.timeout = config["timeout"]
    httpd.server_bind()
    httpd.server_activate()

    # serve payload
    while True:
        r, w, e = select.select([httpd.socket], [], [], httpd.timeout)
        if r:
            httpd.handle_request()
            break
        else:
            raise Exception(f"Timeout after {httpd.timeout} seconds.")

finally:
    # stop threads, remove named pipes and temp_dir
    try:
        cert_thread.join()
    except:
        pass
    try:
        key_thread.join()
    except:
        pass
    try:
        os.remove(cert_fifo_path)
    except:
        pass
    try:
        os.remove(key_fifo_path)
    except:
        pass
    try:
        shutil.rmtree(temp_dir)
    except:
        pass
