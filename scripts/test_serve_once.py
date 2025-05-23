#!/usr/bin/env python
# /// script
# dependencies = [
#   "pyyaml",
#   "cryptography",
# ]
# ///

import http.client
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import re
import threading
import select

from pathlib import Path
from typing import Any, Optional

import yaml
from cryptography import x509
from cryptography.x509 import SubjectKeyIdentifier, AuthorityKeyIdentifier  # Ensure imports
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Add the directory containing serve_once.py to the Python path
# Assuming serve_once.py is in the same directory as test_serve_once.py
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
import serve_once  # noqa: E402


# Function to read output stream non-blockingly
def read_stream(stream, lines_list, stop_event):
    while not stop_event.is_set():
        # Use select for non-blocking read with timeout
        readable, _, _ = select.select([stream], [], [], 0.1)
        if readable:
            line = stream.readline()
            if not line:
                # End of stream
                break
            lines_list.append(line)
        else:
            # No data available, check stop event again
            continue


class TestServeOnce(unittest.TestCase):
    """Base class for serve_once tests, providing common setup and utility methods."""

    def setUp(self):
        """Sets up a basic configuration for testing."""
        # Generate default cert/key for most tests to avoid self-signed generation warnings
        default_certs = serve_once.generate_self_signed_certificate("localhost")
        self.base_config = serve_once.DEFAULT_CONFIG.copy()
        # Short timeout for tests
        self.base_config["timeout"] = 5
        self.base_config["cert"] = default_certs["cert"]
        self.base_config["key"] = default_certs["key"]
        # Default to dynamic port
        self.base_config["serve_port"] = 0
        self.process = None
        self.ca_cert_path = None
        self.client_cert_path = None
        self.client_key_path = None
        self.mtls_server_cert_path = None
        self.mtls_server_key_path = None
        self.ca_key = None
        self.ca_cert = None
        self.stdout_lines = []
        self.stderr_lines = []
        self.stdout_thread = None
        self.stderr_thread = None
        self.stop_read_event = threading.Event()

    def tearDown(self):
        """Cleans up any running processes or temporary files."""
        if self.process:
            # Signal process to terminate if it's running
            if self.process.poll() is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    # Process might have already exited
                    pass

            # Signal reading threads to stop
            self.stop_read_event.set()

            # Wait for the process to terminate
            if self.process.poll() is None:
                # Check again if terminate() worked quickly or process exited
                try:
                    # Main wait for termination
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    print(
                        "Warning: Process did not terminate gracefully after terminate(), killing.",
                        file=sys.stderr,
                    )
                    try:
                        self.process.kill()
                        self.process.wait(timeout=2)  # Wait for kill
                    except ProcessLookupError:
                        # Process might have died before kill
                        pass
                    except subprocess.TimeoutExpired:
                        print(
                            "Warning: Process did not terminate after kill().", file=sys.stderr
                        )
                except ProcessLookupError:
                    # Process exited before wait
                    pass

        # Wait for reading threads to join (do this after process is likely done)
        if self.stdout_thread and self.stdout_thread.is_alive():
            self.stdout_thread.join(timeout=1)
            if self.stdout_thread.is_alive():
                print("Warning: stdout_thread did not join in time.", file=sys.stderr)
        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=1)
            if self.stderr_thread.is_alive():
                print("Warning: stderr_thread did not join in time.", file=sys.stderr)

        # Close process streams
        # Ensure process exists and streams are not None before trying to close
        if self.process:
            if self.process.stdout and not self.process.stdout.closed:
                try:
                    self.process.stdout.close()
                except Exception as e:
                    print(f"Warning: Error closing stdout: {e}", file=sys.stderr)
            if self.process.stderr and not self.process.stderr.closed:
                try:
                    self.process.stderr.close()
                except Exception as e:
                    print(f"Warning: Error closing stderr: {e}", file=sys.stderr)

        # Clean up temporary files
        if self.ca_cert_path and os.path.exists(self.ca_cert_path):
            os.remove(self.ca_cert_path)
        if self.client_cert_path and os.path.exists(self.client_cert_path):
            os.remove(self.client_cert_path)
        if self.client_key_path and os.path.exists(self.client_key_path):
            os.remove(self.client_key_path)
        if self.mtls_server_cert_path and os.path.exists(self.mtls_server_cert_path):
            os.remove(self.mtls_server_cert_path)
        if self.mtls_server_key_path and os.path.exists(self.mtls_server_key_path):
            os.remove(self.mtls_server_key_path)

    def generate_self_signed_ca(self):
        """Generates a self-signed CA certificate and key."""
        self.ca_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
        self.ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(self.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                - serve_once.datetime.timedelta(days=1)
            )
            .not_valid_after(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                + serve_once.datetime.timedelta(days=365)
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(  # SKI for CA
                SubjectKeyIdentifier.from_public_key(self.ca_key.public_key()), critical=False
            )
            .sign(self.ca_key, hashes.SHA256(), default_backend())
        )

    def generate_client_cert(self, common_name="client"):
        """Generates a client certificate signed by the test CA."""
        if not self.ca_cert or not self.ca_key:
            raise ValueError("CA certificate/key not generated before client cert")

        client_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        client_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self.ca_cert.subject)
            .public_key(client_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                - serve_once.datetime.timedelta(days=1)
            )
            .not_valid_after(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                + serve_once.datetime.timedelta(days=365)
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                    ]
                ),
                critical=True,
            )
            .add_extension(  # SKI for client cert
                SubjectKeyIdentifier.from_public_key(client_key.public_key()), critical=False
            )
            .add_extension(  # AKI for client cert (referencing CA's public key)
                AuthorityKeyIdentifier.from_issuer_public_key(self.ca_cert.public_key()),
                critical=False,
            )
            .sign(self.ca_key, hashes.SHA256(), default_backend())
        )
        return client_key, client_cert

    def generate_server_cert_for_mtls(self, common_name="localhost_mtls_server"):
        """Generates a server certificate signed by the test CA, for mTLS."""
        if not self.ca_cert or not self.ca_key:
            raise ValueError("CA certificate/key not generated before server cert for mTLS")

        server_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        server_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self.ca_cert.subject)  # Signed by Test CA
            .public_key(server_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                - serve_once.datetime.timedelta(days=1)
            )
            .not_valid_after(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                + serve_once.datetime.timedelta(days=365)
            )
            .add_extension(  # For server cert
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=True,
            )
            .add_extension(  # For server cert
                x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False
            )
            .add_extension(  # SKI for mTLS server cert
                SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False
            )
            .add_extension(  # AKI for mTLS server cert (referencing CA's public key)
                AuthorityKeyIdentifier.from_issuer_public_key(self.ca_cert.public_key()),
                critical=False,
            )
            .sign(self.ca_key, hashes.SHA256(), default_backend())
        )
        return server_key, server_cert

    def write_temp_file(self, content: str | bytes) -> str:
        """Writes content to a temporary file and returns the path."""
        # Use a context manager to ensure the file is closed before returning path
        fd, temp_path = tempfile.mkstemp(suffix=".pem", text=False)
        with os.fdopen(fd, "wb") as temp_file:
            if isinstance(content, str):
                temp_file.write(content.encode("utf-8"))
            else:
                temp_file.write(content)
        return temp_path

    def write_cert_files(self):
        self.generate_self_signed_ca()
        self.ca_cert_path = self.write_temp_file(
            self.ca_cert.public_bytes(serialization.Encoding.PEM)
        )

        client_key, client_cert = self.generate_client_cert()
        self.client_cert_path = self.write_temp_file(
            client_cert.public_bytes(serialization.Encoding.PEM)
        )
        self.client_key_path = self.write_temp_file(
            client_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        # Generate and write server cert/key for mTLS tests, signed by our CA
        mtls_server_key, mtls_server_cert = self.generate_server_cert_for_mtls()
        self.mtls_server_cert_path = self.write_temp_file(
            mtls_server_cert.public_bytes(serialization.Encoding.PEM)
        )
        self.mtls_server_key_path = self.write_temp_file(
            mtls_server_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    def start_server(
        self, config: dict[str, Any], verbose_test: bool = False
    ) -> subprocess.Popen:
        """Starts the serve_once script, sends config, and returns the running process."""
        config_str = yaml.dump(config)
        command = [sys.executable, os.path.join(script_dir, "serve_once.py"), "--yes"]
        if verbose_test or config.get("request_body_stdout"):
            # Pass verbose if test needs it
            command.append("--verbose")

        # Reset output capture lists and stop event
        self.stdout_lines = []
        self.stderr_lines = []
        self.stop_read_event.clear()

        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Use text mode for easier handling
                text=True,
                # Line buffering
                bufsize=1,
                # Ensure the process group can be killed if needed
                # start_new_session=True # Might be needed on some platforms
            )
        except Exception as e:
            print(f"Error starting subprocess: {e}", file=sys.stderr)
            raise

        # Start threads to capture output non-blockingly
        self.stdout_thread = threading.Thread(
            target=read_stream,
            args=(self.process.stdout, self.stdout_lines, self.stop_read_event),
        )
        self.stderr_thread = threading.Thread(
            target=read_stream,
            args=(self.process.stderr, self.stderr_lines, self.stop_read_event),
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

        # Send configuration via stdin
        try:
            if self.process.stdin:
                self.process.stdin.write(config_str)
                # Signal EOF
                self.process.stdin.close()
            else:
                raise IOError("Subprocess stdin is not available.")
        except (OSError, BrokenPipeError, IOError) as e:
            print(f"Error writing to subprocess stdin: {e}", file=sys.stderr)
            # Stop reading threads and attempt cleanup
            self.stop_read_event.set()
            if self.stdout_thread:
                self.stdout_thread.join(timeout=0.5)
            if self.stderr_thread:
                self.stderr_thread.join(timeout=0.5)
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=1)
            raise RuntimeError(f"Failed to send config to serve_once: {e}") from e

        # Wait for the server to print the "SERVING_ON_PORT: <port>" message (or timeout)
        start_time = time.time()
        port_found = False
        processed_stderr_len = 0  # Keep track of processed stderr lines for verbose_test

        # 5 second timeout for the specific port message
        while time.time() - start_time < 5:
            # Process new stderr lines
            # Create a local copy of self.stderr_lines for thread safety during iteration
            current_stderr_lines = list(self.stderr_lines)

            if verbose_test and len(current_stderr_lines) > processed_stderr_len:
                new_stderr_output = "".join(current_stderr_lines[processed_stderr_len:])
                print(f"Server Stderr: {new_stderr_output}", end="", file=sys.stderr)
            processed_stderr_len = len(current_stderr_lines)

            # Check for the specific port message in all captured stderr lines
            for line in current_stderr_lines:
                match = re.search(r"SERVING_ON_PORT: (\d+)", line)
                if match:
                    port_str = match.group(1)
                    if port_str.isdigit():
                        config["serve_port"] = int(port_str)
                        if verbose_test:
                            print(
                                f"\nFound SERVING_ON_PORT: {config['serve_port']} in stderr."
                            )
                        port_found = True
                        break  # Exit inner loop (line processing)
                    elif verbose_test:
                        print(
                            f"\nWarning: Found 'SERVING_ON_PORT:' but port value '{port_str}' is not a digit.",
                            file=sys.stderr,
                        )

            if port_found:
                break  # Exit outer loop (timeout loop)

            # Check for early exit or critical errors
            if self.process.poll() is not None:
                # Combine all stderr for the error message
                stderr_final = "".join(current_stderr_lines)
                raise RuntimeError(
                    f"Server process exited prematurely (code {self.process.poll()}). Stderr:\n{stderr_final}"
                )

            time.sleep(0.1)  # Small sleep to avoid busy-waiting

        if not port_found:
            self.stop_read_event.set()  # Stop reading threads
            # Wait a bit for threads to actually stop and capture final output
            if self.stdout_thread:
                self.stdout_thread.join(timeout=0.2)
            if self.stderr_thread:
                self.stderr_thread.join(timeout=0.2)

            stdout_final = "".join(self.stdout_lines)
            stderr_final = "".join(self.stderr_lines)  # Use potentially updated list

            if self.process.poll() is None:
                self.process.terminate()
            exit_code = self.process.wait(
                timeout=1
            )  # Wait for termination after a potential kill
            raise TimeoutError(
                f"Server did not print 'SERVING_ON_PORT: <port>' to stderr within timeout. Exit code: {exit_code}\n"
                f"Stdout:\n{stdout_final}\nStderr:\n{stderr_final}"
            )

        # If dynamic port was requested (original config["serve_port"] == 0),
        # ensure it's now set to a non-zero value.
        # The 'serve_port_was_zero' flag is set by the test cases themselves.
        if config.get("serve_port_was_zero", False) and config["serve_port"] == 0:
            raise ValueError(
                "Server was expected to use a dynamic port, but reported port 0 or message not found."
            )

        # Return the running process
        return self.process

    def make_request(
        self,
        method: str,
        path: str,
        port: int,
        hostname: str = "localhost",
        use_ssl: bool = True,
        # Explicit CA for client verification
        ca_cert_path_for_client: str | None = None,
        client_cert: tuple[str, str] | None = None,
        data=None,
        # Shorter timeout for requests
        timeout: float = 3.0,
    ) -> Optional[http.client.HTTPResponse]:
        """Makes an HTTP request to the server. Returns response or None on connection error."""
        conn = None
        try:
            if use_ssl:
                context = ssl.create_default_context()
                # ALWAYS ignore server cert hostname for localhost tests
                context.check_hostname = False
                # Default to ignoring server cert validation unless CA is provided
                context.verify_mode = ssl.CERT_NONE

                if ca_cert_path_for_client:
                    try:
                        context.load_verify_locations(cafile=ca_cert_path_for_client)
                        # Verify server if CA given
                        context.verify_mode = ssl.CERT_REQUIRED
                    except FileNotFoundError:
                        print(
                            f"Warning: CA file not found: {ca_cert_path_for_client}",
                            file=sys.stderr,
                        )
                        # Fall back to no verification or let it fail later? Let it fail.
                    except ssl.SSLError as e:
                        print(
                            f"Warning: Error loading CA file {ca_cert_path_for_client}: {e}",
                            file=sys.stderr,
                        )
                        raise

                if client_cert:
                    try:
                        context.load_cert_chain(client_cert[0], client_cert[1])
                    except FileNotFoundError:
                        print(
                            f"Warning: Client cert/key file not found: {client_cert}",
                            file=sys.stderr,
                        )
                        raise
                    except ssl.SSLError as e:
                        print(
                            f"Warning: Error loading client cert/key {client_cert}: {e}",
                            file=sys.stderr,
                        )
                        raise

                conn = http.client.HTTPSConnection(
                    hostname, port, context=context, timeout=timeout
                )
            else:
                conn = http.client.HTTPConnection(hostname, port, timeout=timeout)

            # Encode data if it's a string
            body = data.encode("utf-8") if isinstance(data, str) else data
            conn.request(method, path, body=body)
            response = conn.getresponse()
            # Read the body now to allow closing connection
            response_body = response.read()
            # Attach body to response object for later access in tests
            response.body_content = response_body
            return response
        except (
            ConnectionRefusedError,
            socket.timeout,
            ssl.SSLError,
            http.client.HTTPException,
        ) as e:
            print(f"HTTP request failed: {type(e).__name__}: {e}", file=sys.stderr)
            # Print server output for debugging
            print("--- Server Stdout ---", file=sys.stderr)
            print("".join(self.stdout_lines), file=sys.stderr)
            print("--- Server Stderr ---", file=sys.stderr)
            print("".join(self.stderr_lines), file=sys.stderr)
            # Indicate failure
            return None
        finally:
            if conn:
                conn.close()

    def wait_for_server(self, port: int, timeout: float = 5.0) -> None:
        """Waits for the server to be listening on the specified port."""
        if port == 0:
            raise ValueError("Port cannot be 0 for wait_for_server")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Use SSL context that ignores server cert validation for the check
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                with socket.create_connection(("localhost", port), timeout=0.5) as sock:
                    with context.wrap_socket(sock, server_hostname="localhost") as ssock:
                        # Optional: could do a minimal handshake check here if needed
                        # print(f"Server listening check on port {port} successful.")
                        return  # Server is up
            except (ConnectionRefusedError, OSError, socket.timeout, ssl.SSLError) as e:
                # print(f"Waiting for server on port {port}... ({type(e).__name__})") # Debug print
                # Check if the server process died unexpectedly
                if self.process and self.process.poll() is not None:
                    raise RuntimeError(
                        f"Server process died while waiting for port {port}. Exit code: {self.process.poll()}"
                    )
                time.sleep(0.2)  # Wait before retrying
        raise TimeoutError(
            f"Server did not start listening on port {port} within the timeout period."
        )

    def assert_server_exit_code(self, expected_code: int, timeout: float = 3.0):
        """Waits for the server process to exit and asserts its exit code."""
        try:
            exit_code = self.process.wait(timeout=timeout)
            self.assertEqual(
                exit_code,
                expected_code,
                f"Server exited with code {exit_code}, expected {expected_code}",
            )
        except subprocess.TimeoutExpired:
            self.fail(
                f"Server did not exit within {timeout} seconds (expected exit code {expected_code})."
            )
        finally:
            # Ensure reading threads are stopped after process exit
            self.stop_read_event.set()
            if self.stdout_thread:
                self.stdout_thread.join(timeout=0.5)
            if self.stderr_thread:
                self.stderr_thread.join(timeout=0.5)

    # --- Test Cases ---

    def test_basic_get(self):
        """Tests a basic GET request."""
        config = self.base_config.copy()
        config["payload"] = "Hello, world!"
        config["header"] = {"X-Test": "test_value"}
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/", port)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body_content.decode("utf-8"), "Hello, world!")
        self.assertEqual(response.getheader("X-Test"), "test_value")

        # Server should exit with 0 after successful request
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_basic_post(self):
        """Tests a basic POST request."""
        config = self.base_config.copy()
        config["request_method"] = "POST"
        config["payload"] = "POST response"
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("POST", "/", port, data="Some POST data")
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body_content.decode("utf-8"), "POST response")
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_custom_headers(self):
        """Tests custom headers."""
        config = self.base_config.copy()
        config["header"] = {"X-Custom-Header": "MyValue", "Content-Type": "text/plain"}
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/", port)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("X-Custom-Header"), "MyValue")
        self.assertEqual(response.getheader("Content-Type"), "text/plain")
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_custom_payload(self):
        """Tests custom payload."""
        config = self.base_config.copy()
        config["payload"] = '{"message": "Custom payload"}'
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/", port)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.body_content.decode("utf-8"), '{"message": "Custom payload"}'
        )
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_invalid_path(self):
        """Tests an invalid request path."""
        config = self.base_config.copy()
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/invalid", port)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 404)

        # Check if the server is still running (should not exit on error)
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on invalid path request"
        )
        # Manually terminate for cleanup
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)  # SIGTERM is -15

    def test_invalid_method(self):
        """Tests an invalid request method."""
        config = self.base_config.copy()
        config["request_method"] = "GET"  # Expect GET
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("OPTIONS", "/", port)  # Send OPTIONS
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 405)
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on invalid method request"
        )
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)

    def test_invalid_client_ip(self):
        """Tests an invalid client IP."""
        config = self.base_config.copy()
        config["request_ip"] = "1.2.3.4"  # Unlikely IP for localhost connection
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/", port)  # Request comes from 127.0.0.1
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 403)
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on invalid IP request"
        )
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)

    def test_timeout(self):
        """Tests server timeout."""
        config = self.base_config.copy()
        config["timeout"] = 1  # Short timeout
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        # Don't make any requests, just wait for the server to time out
        # Wait slightly longer than the server's timeout
        self.assert_server_exit_code(1, timeout=config["timeout"] + 2)

    def test_self_signed_cert(self):
        """Tests automatic self-signed certificate generation."""
        config = self.base_config.copy()
        config["cert"] = None  # Trigger self-signed generation
        config["key"] = None
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config, verbose_test=True)  # Verbose to see warning
        port = config["serve_port"]
        self.wait_for_server(port)

        # Check stderr for the warning message
        stderr_output = "".join(self.stderr_lines)
        self.assertIn("Warning: no cert or key set", stderr_output)

        response = self.make_request("GET", "/", port)
        self.assertIsNotNone(response, "Request failed (check server logs/stderr)")
        self.assertEqual(response.status, 200)
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_mtls_valid_cert(self):
        """Tests mTLS with a valid client certificate."""
        self.write_cert_files()  # Generates CA, client cert/key

        config = self.base_config.copy()
        # Use mTLS-specific server cert/key signed by our CA
        config["cert"] = Path(self.mtls_server_cert_path).read_text()
        config["key"] = Path(self.mtls_server_key_path).read_text()
        config["mtls"] = True
        config["ca_cert"] = Path(
            self.ca_cert_path
        ).read_text()  # Server needs CA to verify client
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request(
            "GET",
            "/",
            port,
            client_cert=(self.client_cert_path, self.client_key_path),
            # Client needs CA to verify server (even if self-signed by same CA)
            ca_cert_path_for_client=self.ca_cert_path,
        )
        self.assertIsNotNone(response, "mTLS request failed")
        self.assertEqual(response.status, 200)
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_mtls_no_cert(self):
        """Tests mTLS without a client certificate provided by client."""
        self.write_cert_files()
        config = self.base_config.copy()
        config["cert"] = Path(self.client_cert_path).read_text()
        config["key"] = Path(self.client_key_path).read_text()
        config["mtls"] = True  # Server requires client cert
        config["ca_cert"] = Path(self.ca_cert_path).read_text()
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        # Make request *without* client cert details
        # Expecting SSLError during handshake
        response = self.make_request(
            "GET",
            "/",
            port,
            ca_cert_path_for_client=self.ca_cert_path,  # Client still verifies server
        )
        self.assertIsNone(
            response, "Request should have failed with SSL error, but got a response"
        )

        # Server should still be running
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on failed mTLS handshake"
        )
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)

    def test_mtls_invalid_cert_ca(self):
        """Tests mTLS with a client certificate signed by a different CA."""
        self.write_cert_files()  # Main CA and client cert

        # Generate a *different* CA and a client cert signed by it
        other_ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_ca_cert_obj = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Other Test CA")])
            )
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Other Test CA")]))
            .public_key(other_ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                - serve_once.datetime.timedelta(days=1)
            )
            .not_valid_after(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                + serve_once.datetime.timedelta(days=365)
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(other_ca_key, hashes.SHA256(), default_backend())
        )

        other_client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_client_cert_obj = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "other_client")]))
            .issuer_name(
                other_ca_cert_obj.subject  # Signed by OTHER CA
            )
            .public_key(other_client_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                - serve_once.datetime.timedelta(days=1)
            )
            .not_valid_after(
                serve_once.datetime.datetime.now(serve_once.datetime.timezone.utc)
                + serve_once.datetime.timedelta(days=365)
            )
            .sign(other_ca_key, hashes.SHA256(), default_backend())
        )  # Sign with OTHER CA key

        other_client_cert_path = self.write_temp_file(
            other_client_cert_obj.public_bytes(serialization.Encoding.PEM)
        )
        other_client_key_path = self.write_temp_file(
            other_client_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        # Configure server with the *original* CA
        config = self.base_config.copy()
        config["cert"] = Path(self.client_cert_path).read_text()  # Server's own cert
        config["key"] = Path(self.client_key_path).read_text()
        config["mtls"] = True
        config["ca_cert"] = Path(self.ca_cert_path).read_text()  # Server trusts original CA
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        # Make request using the client cert signed by the *other* CA
        response = self.make_request(
            "GET",
            "/",
            port,
            client_cert=(other_client_cert_path, other_client_key_path),
            ca_cert_path_for_client=self.ca_cert_path,  # Client trusts original CA for server cert
        )
        self.assertIsNone(
            response, "Request should have failed SSL verification, but got a response"
        )

        # Server should still be running
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on invalid client CA"
        )
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)

        # Clean up extra certs
        os.remove(other_client_cert_path)
        os.remove(other_client_key_path)

    def test_mtls_valid_cert_valid_cn(self):
        """Tests mTLS with client ID check (valid CN)."""
        self.write_cert_files()  # Generates client cert with CN="client"

        config = self.base_config.copy()
        # Use mTLS-specific server cert/key signed by our CA
        config["cert"] = Path(self.mtls_server_cert_path).read_text()
        config["key"] = Path(self.mtls_server_key_path).read_text()
        config["mtls"] = True
        config["ca_cert"] = Path(self.ca_cert_path).read_text()
        config["mtls_clientid"] = "client"  # Server expects CN="client"
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request(
            "GET",
            "/",
            port,
            client_cert=(self.client_cert_path, self.client_key_path),
            ca_cert_path_for_client=self.ca_cert_path,
        )
        self.assertIsNotNone(response, "mTLS request failed")
        self.assertEqual(response.status, 200)
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_mtls_valid_cert_invalid_cn(self):
        """Tests mTLS with client ID check (invalid CN)."""
        self.write_cert_files()  # Generates client cert with CN="client"

        config = self.base_config.copy()
        # Use mTLS-specific server cert/key signed by our CA
        config["cert"] = Path(self.mtls_server_cert_path).read_text()
        config["key"] = Path(self.mtls_server_key_path).read_text()
        config["mtls"] = True
        config["ca_cert"] = Path(self.ca_cert_path).read_text()
        config["mtls_clientid"] = "wrong_client"  # Server expects different CN
        config["serve_port_was_zero"] = config["serve_port"] == 0

        self.process = self.start_server(config)
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request(
            "GET",
            "/",
            port,
            client_cert=(self.client_cert_path, self.client_key_path),
            ca_cert_path_for_client=self.ca_cert_path,
        )
        # The server should reject this *after* the TLS handshake
        # It sends a 401 Unauthorized error
        self.assertIsNotNone(response, "Request failed unexpectedly")
        self.assertEqual(response.status, 401)

        # Server should still be running
        self.assertIsNone(
            self.process.poll(), "Server exited unexpectedly on invalid client CN"
        )
        self.process.terminate()
        self.assert_server_exit_code(-15, timeout=1)

    def test_dynamic_port(self):
        """Tests dynamic port allocation (serve_port: 0)."""
        config = self.base_config.copy()
        config["serve_port"] = 0  # Explicitly request dynamic port
        config["serve_port_was_zero"] = True

        self.process = self.start_server(config)

        # Verify start_server assigned a dynamic port correctly
        self.assertGreater(config["serve_port"], 0, "Dynamic port was not assigned")
        port = config["serve_port"]
        self.wait_for_server(port)

        response = self.make_request("GET", "/", port)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

    def test_request_body_stdout(self):
        """Tests echoing request body to server's stdout."""
        config = self.base_config.copy()
        config["request_body_stdout"] = True
        config["request_method"] = "POST"
        config["serve_port_was_zero"] = config["serve_port"] == 0

        # Start server (will also pass --verbose to serve_once.py)
        self.process = self.start_server(config, verbose_test=True)
        port = config["serve_port"]
        self.wait_for_server(port)

        request_data = '{"key": "value", "data": [1, 2, 3]}'
        response = self.make_request("POST", "/", port, data=request_data)
        self.assertIsNotNone(response, "Request failed")
        self.assertEqual(response.status, 200)

        # Server should exit with 0
        self.assert_server_exit_code(0, timeout=config["timeout"] + 1)

        # Now check the captured stdout (after process exit)
        stdout_output = "".join(self.stdout_lines)
        # The request body should be printed exactly to stdout
        # It might be preceded/followed by other verbose output, so use 'in'
        self.assertIn(request_data, stdout_output.strip())  # Strip potential extra newlines


if __name__ == "__main__":
    # Increase verbosity for unittest output
    # To see verbose output from serve_once.py during tests,
    # set verbose_test=True in start_server calls or globally.
    unittest.main(verbosity=2)
