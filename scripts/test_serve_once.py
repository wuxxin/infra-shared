import tempfile
import os
import pytest
import aiohttp
import datetime
import ssl
import time
import threading
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from serve_once import serve_once, verbose_print, generate_self_signed_certificate

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "serve_once.py")


def generate_ca_signed_certificate(
    hostname, ca_cert_path, ca_key_path, client_cert=False, client_cn=None
):
    with open(ca_cert_path, "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    with open(ca_key_path, "rb") as f:
        ca_private_key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    )
    builder = builder.issuer_name(ca_cert.subject)
    builder = builder.public_key(private_key.public_key())
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.not_valid_before(datetime.datetime.utcnow())
    builder = builder.not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    )
    builder = builder.add_extension(
        x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
    )
    if client_cert:
        eku = [x509.ExtendedKeyUsageOID.CLIENT_AUTH]
    else:
        eku = [x509.ExtendedKeyUsageOID.SERVER_AUTH]
    builder = builder.add_extension(x509.ExtendedKeyUsage(eku), critical=True)

    certificate = builder.sign(
        private_key=ca_private_key, algorithm=hashes.SHA256(), backend=default_backend()
    )

    return {
        "key": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        "cert": certificate.public_bytes(serialization.Encoding.PEM),
    }


@pytest.fixture
def temp_cert_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


async def run_server_async(config):
    """Runs the serve_once server in a separate thread and returns the server address."""
    server_ready_event = threading.Event()
    server_address_container = {}

    def start_server():
        # Call serve_once directly
        httpd = serve_once(config)
        # Get port after server starts
        server_address_container["port"] = httpd.server_address[1]
        server_ready_event.set()
        try:
            # Keep serving until shutdown
            httpd.serve_forever()
        except Exception as e:
            verbose_print(f"Server thread exception: {e}")
        finally:
            httpd.server_close()
            verbose_print("Server thread finished")

    # Daemon thread so it exits when test ends
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()
    # Wait for server to start, with timeout
    server_ready_event.wait(timeout=10)

    if not server_ready_event.is_set():
        raise TimeoutError("Server failed to start within timeout")

    return server_address_container["port"]


async def test_self_signed_cert(temp_cert_dir):
    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "payload": "test_payload",
    }
    port = await run_server_async(config)
    assert port > 0

    url = f"https://localhost:{port}/"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:  # Disable SSL verify for self-signed
        async with session.get(url) as resp:
            assert resp.status == 200
            text = await resp.text()
            assert text == "test_payload"


async def test_full_mtls_success(temp_cert_dir):
    ca_cert_path = os.path.join(temp_cert_dir, "ca.crt")
    ca_key_path = os.path.join(temp_cert_dir, "ca.key")
    server_cert_path = os.path.join(temp_cert_dir, "server.crt")
    server_key_path = os.path.join(temp_cert_dir, "server.key")
    client_cert_path = os.path.join(temp_cert_dir, "client.crt")
    client_key_path = os.path.join(temp_cert_dir, "client.key")

    ca_cert_key = generate_self_signed_certificate("ca.example.com")
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert_key["cert"])
    with open(ca_key_path, "wb") as f:
        f.write(ca_cert_key["key"])

    server_cert_key = generate_ca_signed_certificate(
        "localhost", ca_cert_path, ca_key_path
    )
    with open(server_cert_path, "wb") as f:
        f.write(server_cert_key["cert"])
    with open(server_key_path, "wb") as f:
        f.write(server_cert_key["key"])

    client_cert_key = generate_ca_signed_certificate(
        "client.example.com",
        ca_cert_path,
        ca_key_path,
        client_cert=True,
        client_cn="client.example.com",
    )
    with open(client_cert_path, "wb") as f:
        f.write(client_cert_key["cert"])
    with open(client_key_path, "wb") as f:
        f.write(client_cert_key["key"])

    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "payload": "mtls_test_payload",
        "cert": server_cert_key["cert"].decode(),
        "key": server_cert_key["key"].decode(),
        "ca_cert": ca_cert_key["cert"].decode(),
        "mtls": True,
        "mtls_clientid": "client.example.com",
    }
    port = await run_server_async(config)
    assert port > 0

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(ca_cert_path)
    ssl_ctx.load_cert_chain(client_cert_path, client_key_path)

    url = f"https://localhost:{port}/"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx)
    ) as session:
        async with session.get(url) as resp:
            assert resp.status == 200
            text = await resp.text()
            assert text == "mtls_test_payload"


async def test_timeout():
    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 1,
        "payload": "timeout_test_payload",
    }
    port = await run_server_async(config)
    assert port > 0

    url = f"https://localhost:{port}/"
    start_time = time.time()
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        with pytest.raises(
            aiohttp.ClientConnectionError
        ):  # Connection error as server exits
            async with session.get(
                url, timeout=5
            ) as resp:  # client timeout > server timeout
                pass  # Should not reach here
    end_time = time.time()
    # In this in-process version, the server thread might not exit immediately on timeout.
    # The timeout in serve_once will stop handling *new* requests, but the thread keeps running.
    # We can't reliably check process exit code here in the same way as with subprocess.
    # Instead, we just check that the client gets a connection error relatively quickly.
    assert (
        end_time - start_time
    ) < 3  # Check that client timeout is reached reasonably quickly


async def test_invalid_path(temp_cert_dir):
    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "request_path": "/valid_path",
        "payload": "invalid_path_payload",
    }
    port = await run_server_async(config)
    assert port > 0

    url = f"https://localhost:{port}/invalid_path"  # Wrong path
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        async with session.get(url) as resp:
            assert resp.status == 404  # Not Found

    url = f"https://localhost:{port}/valid_path"  # Correct path to allow exit
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        async with session.get(url) as resp:
            assert resp.status == 200


async def test_invalid_method(temp_cert_dir):
    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "request_method": "GET",
        "payload": "invalid_method_payload",
    }
    port = await run_server_async(config)
    assert port > 0

    url = f"https://localhost:{port}/"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        async with session.post(url) as resp:  # Wrong method
            assert resp.status == 405  # Method Not Allowed

    url = f"https://localhost:{port}/"  # Correct method to allow exit
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        async with session.get(url) as resp:
            assert resp.status == 200


async def test_invalid_client_cert_mtls(temp_cert_dir):
    ca_cert_path = os.path.join(temp_cert_dir, "ca.crt")
    ca_key_path = os.path.join(temp_cert_dir, "ca.key")
    server_cert_path = os.path.join(temp_cert_dir, "server.crt")
    server_key_path = os.path.join(temp_cert_dir, "server.key")
    client_cert_path = os.path.join(temp_cert_dir, "client.crt")
    client_key_path = os.path.join(temp_cert_dir, "client.key")
    invalid_client_cert_path = os.path.join(temp_cert_dir, "invalid_client.crt")
    invalid_client_key_path = os.path.join(temp_cert_dir, "invalid_client.key")

    ca_cert_key = generate_self_signed_certificate("ca.example.com")
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert_key["cert"])
    with open(ca_key_path, "wb") as f:
        f.write(ca_cert_key["key"])

    server_cert_key = generate_ca_signed_certificate(
        "localhost", ca_cert_path, ca_key_path
    )
    with open(server_cert_path, "wb") as f:
        f.write(server_cert_key["cert"])
    with open(server_key_path, "wb") as f:
        f.write(server_cert_key["key"])

    client_cert_key = generate_ca_signed_certificate(
        "client.example.com",
        ca_cert_path,
        ca_key_path,
        client_cert=True,
        client_cn="client.example.com",
    )
    with open(client_cert_path, "wb") as f:
        f.write(client_cert_key["cert"])
    with open(client_key_path, "wb") as f:
        f.write(client_cert_key["key"])

    invalid_client_cert_key = generate_ca_signed_certificate(
        "wrongclient.example.com",
        ca_cert_path,
        ca_key_path,
        client_cert=True,
        client_cn="wrongclient.example.com",
    )
    with open(invalid_client_cert_path, "wb") as f:
        f.write(invalid_client_cert_key["cert"])
    with open(invalid_client_key_path, "wb") as f:
        f.write(invalid_client_cert_key["key"])

    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "payload": "invalid_client_cert_payload",
        "cert": server_cert_key["cert"].decode(),
        "key": server_cert_key["key"].decode(),
        "ca_cert": ca_cert_key["cert"].decode(),
        "mtls": True,
        "mtls_clientid": "client.example.com",
    }
    port = await run_server_async(config)
    assert port > 0

    ssl_ctx_valid = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx_valid.load_verify_locations(ca_cert_path)
    ssl_ctx_valid.load_cert_chain(client_cert_path, client_key_path)

    ssl_ctx_invalid = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx_invalid.load_verify_locations(ca_cert_path)
    ssl_ctx_invalid.load_cert_chain(invalid_client_cert_path, invalid_client_key_path)

    url = f"https://localhost:{port}/"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx_invalid)
    ) as session:  # Invalid client cert
        async with session.get(url) as resp:
            assert resp.status == 401  # Unauthorized

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx_valid)
    ) as session:  # Valid client cert to allow exit
        async with session.get(url) as resp:
            assert resp.status == 200


async def test_missing_client_cert_mtls(temp_cert_dir):
    ca_cert_path = os.path.join(temp_cert_dir, "ca.crt")
    ca_key_path = os.path.join(temp_cert_dir, "ca.key")
    server_cert_path = os.path.join(temp_cert_dir, "server.crt")
    server_key_path = os.path.join(temp_cert_dir, "server.key")

    ca_cert_key = generate_self_signed_certificate("ca.example.com")
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert_key["cert"])
    with open(ca_key_path, "wb") as f:
        f.write(ca_cert_key["key"])

    server_cert_key = generate_ca_signed_certificate(
        "localhost", ca_cert_path, ca_key_path
    )
    with open(server_cert_path, "wb") as f:
        f.write(server_cert_key["cert"])
    with open(server_key_path, "wb") as f:
        f.write(server_cert_key["key"])

    config = {
        "serve_port": 0,  # Let OS choose port
        "timeout": 5,
        "payload": "missing_client_cert_payload",
        "cert": server_cert_key["cert"].decode(),
        "key": server_cert_key["key"].decode(),
        "ca_cert": ca_cert_key["cert"].decode(),
        "mtls": True,
        "mtls_clientid": "client.example.com",
    }
    port = await run_server_async(config)
    assert port > 0

    ssl_ctx_no_client_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx_no_client_cert.load_verify_locations(ca_cert_path)
    # ssl_ctx_no_client_cert.load_cert_chain() # No client cert loaded

    ssl_ctx_valid_client_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx_valid_client_cert.load_verify_locations(ca_cert_path)
    client_cert_key = generate_ca_signed_certificate(
        "client.example.com",
        ca_cert_path,
        ca_key_path,
        client_cert=True,
        client_cn="client.example.com",
    )
    client_cert_path_valid = os.path.join(temp_cert_dir, "valid_client.crt")
    client_key_path_valid = os.path.join(temp_cert_dir, "valid_client.key")
    with open(client_cert_path_valid, "wb") as f:
        f.write(client_cert_key["cert"])
    with open(client_key_path_valid, "wb") as f:
        f.write(client_cert_key["key"])
    ssl_ctx_valid_client_cert.load_cert_chain(
        client_cert_path_valid, client_key_path_valid
    )

    url = f"https://localhost:{port}/"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx_no_client_cert)
    ) as session:  # Missing client cert
        with pytest.raises(
            aiohttp.ClientConnectorCertificateError
        ):  # Connection error - server requires client cert
            async with session.get(url) as resp:
                pass  # Should not reach here

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx_valid_client_cert)
    ) as session:  # Valid client cert to allow exit
        async with session.get(url) as resp:
            assert resp.status == 200
