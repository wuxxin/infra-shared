#!/usr/bin/env python
"""serve a HTTPS path once, use STDIN for yaml based configuration and payload, STDOUT for request_body

- <yaml-from-STDIN> | $0 --yes | [<request_body-to-STDOUT>]
- as one time secure data serve for eg. ignition data
- as webhook on demand where the POST data is send to STDOUT and processed by other tools

will wait until timeout in seconds is reached, where it will exit 1
will exit 0 after one sucessful request

- if key or cert is None, a temporary selfsigned cert will be created
- if mtls is true, a ca_cert must be set, and a mandatory client certificate is needed to connect
- if mtls_clientid is not None, the correct id of the client certificate is also needed to connect
- if port_mapping:natpmp is true, sends a port mapping request to the gateway, to be reachable from outside
- uses buildin python except yaml and cryptography if a temporary certificate needs to be created
- invalid request paths, invalid request methods, invalid or missing client certificates
    return an request error, but do not cause the exit of the program.
    only a sucessful transmission or a timeout will end execution.
    TODO: this is currently not true, their are exceptions needed to pass

"""

import argparse
import datetime
import http.server
import os
import select
import shutil
import socket
import ssl
import sys
import tempfile
import threading

import yaml


def verbose_print(message):
    if args.verbose:
        print(message, file=sys.stderr)


def write_cert(cert_fifo_path, cert):
    with open(cert_fifo_path, "wb") as cert_fifo:
        cert_fifo.write(cert)


def write_key(key_fifo_path, key):
    with open(key_fifo_path, "wb") as key_fifo:
        key_fifo.write(key)


def gateway_ip():
    try:
        gateway_addr = socket.gethostbyname(socket.gethostname())
        if (
            not socket.inet_pton(socket.AF_INET, gateway_addr)
            or gateway_addr.startswith("127.")
            or gateway_addr.startswith("::1")
        ):
            gateway_addr = None
    except socket.gaierror:
        gateway_addr = None
    return gateway_addr


def natpmp_port_mapping(public_port, private_port, gateway_ip, lifetime_sec=3600, retry=9):
    pass


def natpmp_delete_mapping(outsideport, gateway_ip):
    pass


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
        .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
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


class ServeOneRequestHandler(http.server.BaseHTTPRequestHandler):
    """requesthandler that only answers to one specific request with conditions configured in config[]"""

    def verbose_error(self, code: int, message: str | None = None, explain: str | None = None):
        self.send_error(code, message, explain)
        if args.verbose:
            print("{}: {}".format(code, message), file=sys.stderr)

    def log_message(self, format, *args):
        if args.verbose:
            # only call the original method if verbose
            super().log_message(format, *args)

    def get_client_cert_common_name(self):
        if "subject" in self.connection.getpeercert():
            subject = dict(x[0] for x in self.client_certificate["subject"])
            if "commonName" in subject:
                return subject["commonName"]
        return None

    def handle_command(self):
        """
        - client_address: (host, port) tuple
        - command, path and version: broken-down request line
        - headers (email.message.Message): header information
        - rfile: file object open for reading at the start of the optional input data part
        - wfile: file object open for writing
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


def serve_once(config):
    """serve one piece of data for one successful request or until a timeout is reached"""

    try:
        # workaround for load_cert_chain(certfile,keyfile), which only works with "real" files
        # create named pipes for cert and key under the /run/user/<uid>/ directory
        temp_dir = tempfile.mkdtemp(dir=os.path.join("/run/user", str(os.getuid())))
        cert_fifo_path = os.path.join(temp_dir, "cert.fifo")
        key_fifo_path = os.path.join(temp_dir, "key.fifo")
        os.mkfifo(cert_fifo_path)
        os.mkfifo(key_fifo_path)

        # Create and start threads to write to named pipes
        cert_thread = threading.Thread(
            target=write_cert, args=(cert_fifo_path, config["cert"])
        )
        key_thread = threading.Thread(target=write_key, args=(key_fifo_path, config["key"]))
        cert_thread.start()
        key_thread.start()

        if config["port_mapping"]["natpmp"]:
            natpmp_port_mapping(
                public_port=config["port_mapping"]["public_port"],
                private_port=config["serve_port"],
                gateway_ip=config["port_mapping"]["gateway_ip"],
            )

        # create HTTPS server
        httpd = http.server.HTTPServer(
            (config["serve_ip"], config["serve_port"]),
            ServeOneRequestHandler,
            bind_and_activate=False,
        )
        httpd.timeout = config["timeout"]
        httpd.socket = ssl.wrap_socket(
            httpd.socket, certfile=cert_fifo_path, keyfile=key_fifo_path, server_side=True
        )
        if config["ca_cert"]:
            #     ssl_ctx.load_verify_locations(cadata=config["ca_cert"])
            #     if config["mtls"]:
            #         ssl_ctx.verify_mode = ssl.CERT_REQUIRED
            pass
        httpd.server_bind()
        httpd.server_activate()

        # serve payload, exit 1 on timeout, exit 0 on succesful request
        while True:
            r, w, e = select.select([httpd.socket], [], [], httpd.timeout)
            if r:
                httpd.handle_request()
                if httpd.RequestHandlerClass.response_code == 200:
                    break
            else:
                sys.exit(1)

    # delete port mapping, stop threads, remove named pipes and temp_dir
    finally:
        try:
            if config["port_mapping"]["natpmp"]:
                natpmp_delete_mapping(
                    public_port=config["port_mapping"]["public_port"],
                    gateway_ip=config["port_mapping"]["gateway_ip"],
                )
        except:
            pass
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


# configure defaults
default_config_str = """
request_ip:
request_path: "/"
request_method: "GET"
request_body_to_stdout: false
serve_ip: 0.0.0.0
serve_port: 8443
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
# port_mapping:.* request a port_mapping to be reachable from outside
port_mapping:
  natpmp: false
  public_port:
  gateway_ip:
"""
default_config = yaml.safe_load(default_config_str)
default_short = ", ".join(["{}: {}".format(k, v) for k, v in default_config.items()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__ + "\ndefaults:\n{}\n".format(default_short),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="Log and Warnings to stderr"
    )
    parser.add_argument("--yes", action="store_true", required=True, help="Confirm execution")

    if not sys.argv[1:]:  # print help and exit if called without parameter
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
        verbose_print("Warning: no cert or key set, creating temporary selfsigned certificate")
        cert_key_dict = generate_self_signed_certificate(config["hostname"])
        config["cert"] = cert_key_dict["cert"]
        config["key"] = cert_key_dict["key"]

    if config["port_mapping"]["natpmp"]:
        if not config["port_mapping"]["public_port"]:
            config["port_mapping"]["public_port"] = config["serve_port"]
        if not config["port_mapping"]["gateway_ip"]:
            config["port_mapping"]["gateway_ip"] = gateway_ip()

    serve_once(config)
