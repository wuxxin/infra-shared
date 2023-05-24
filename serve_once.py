import argparse
import http.server
import select
import shutil
import socketserver
import ssl
import sys
import tempfile
import os
import yaml


default_config_str = """
# mandatory: serve_port, cert, key
request_ip:
request_path: "/"
request_type: "GET"
request_body_to_stdout: true
serve_ip: 0.0.0.0
timeout: 30
ca_cert:
mtls: false
mtls_clientid:
metadata:
data:
"""


def usage():
    print(
        """serve a HTTPS path once, using stdin for configuration and data

+ call with: `cat config.yaml | $0 --yes`

will exit 0 after one sucessful request,
but continue to wait until timeout (specified in seconds), where it will exit 1.

invalid or missing client certificates, invalid request paths or invalid request methods are ignored
and do not cause exit of the program. only a sucessful transmission or a timeout will end execution.

if mtls is true, then ca_cert must be set, and a mandatory client certificate is needed to connect.
if mtls_clientid is not None, the correct id of the clientcertificate is needed to connect.

+ config defaults
```yaml
"""
        + default_config
        + """
```

+ example config

```yaml
request_ip: 1.2.3.4
request_path: "/ignition.ign"
request_body_to_stdout: true
serve_port: 7443
timeout: 30
ca_cert: |
  xxxx
cert: |
  xxxx
key: |
  xxxx
mtls: false
metadata:
  x: y
data: |
  data payload
```

""",
        file=sys.stderr,
    )


# RequestHandler
class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def address_allowed(self):
        return self.headers.get("X-Real-IP").startswith(config["request_ip"])

    def do_GET(self):
        if not self.address_allowed():
            self.send_error(403, "Forbidden")
        else:
            # Serve the single document
            super().do_GET()

            # Exit the server after serving one request
            self.server.shutdown()


# Parse command line arguments
parser = argparse.ArgumentParser(description="serving a HTTPS path once")
parser.add_argument("--yes", action="store_true", help="Confirm execution.")
args = parser.parse_args()
if not args.yes:
    print("Please confirm execution with --yes flag.", file=sys.stderr)
    usage()
    sys.exit(1)

# Read YAML defaults and merge with YAML from stdin
default_config = yaml.safe_load(default_config_str)
loaded_config = yaml.safe_load(sys.stdin.read())
config = {**default_config, **loaded_config}


try:
    # workaround for load_cert_chain(certfile,keyfile), which only works with "real" files
    # create named pipes for cert and key
    temp_dir = tempfile.mkdtemp(dir=os.path.expanduser("~"))
    cert_fifo_path = os.path.join(temp_dir, "cert.fifo")
    key_fifo_path = os.path.join(temp_dir, "key.fifo")
    os.mkfifo(cert_fifo_path)
    os.mkfifo(key_fifo_path)
    # write cert and key to named pipes
    open(cert_fifo_path, "w").write(config["cert"])
    open(key_fifo_path, "w").write(config["key"])

    # Set up SSL context
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile=cert_fifo_path, keyfile=key_fifo_path)
    if config.get("ca_cert", None):
        ssl_ctx.load_verify_locations(cafile=config["ca_cert"])
        if config.get("mtls", False):
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    # Set up HTTP context
    HandlerClass = MyHTTPRequestHandler
    HandlerClass.protocol_version = "HTTP/1.0"
    HandlerClass.ssl_ctx = ssl_ctx

    # create HTTPS server
    httpd = socketserver.TCPServer(("0.0.0.0", config["serve_port"]), HandlerClass)

    # serve payload
    while True:
        try:
            r, w, e = select.select([httpd.socket], [], [], httpd.timeout)
            if r:
                httpd.handle_request()
                break
            else:
                raise Exception(f"Timeout after {httpd.timeout} seconds.")
        except KeyboardInterrupt:
            break
finally:
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

# Exit with success
sys.exit(0)
