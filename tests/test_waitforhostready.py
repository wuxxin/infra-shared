import pytest
from pulumi.automation import Stack
import pulumi
import os
import threading
import time
import paramiko
from pathlib import Path
from .utils import add_pulumi_program
import socketserver
import logging
import tempfile

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class SSHServerHandler(paramiko.ServerInterface):
    def __init__(self, server):
        self.server = server
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "publickey"

    def check_channel_exec_request(self, channel, command):
        command_str = command.decode("utf-8")
        logging.info(f"SSHServer: Received exec request: {command_str}")
        file_to_exist = command_str.split(" ")[-1]

        with self.server.files_lock:
            file_found = file_to_exist in self.server.files

        if file_found:
            logging.info(f"SSHServer: File '{file_to_exist}' found. Returning exit status 0.")
            channel.send_exit_status(0)
        else:
            logging.info(
                f"SSHServer: File '{file_to_exist}' not found. Returning exit status 1."
            )
            channel.send_exit_status(1)

        self.event.set()
        return True


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ParamikoSSHServer:
    def __init__(self, host, port, host_key_path):
        self.host = host
        self.port = port
        self.host_key_path = host_key_path
        self.startup_delay = 0
        self.unavailable_after = 0
        self.rebirth_delay = 10
        self.server = None
        self.server_thread = None
        self.files = set()
        self.files_lock = threading.Lock()
        self.server_started = threading.Event()
        self.is_available = threading.Event()

    def _server_lifecycle(self):
        class Handler(socketserver.BaseRequestHandler):
            def handle(this_handler):
                if not self.is_available.is_set():
                    logging.info("SSHServer: Connection refused as server is unavailable.")
                    this_handler.request.close()
                    return

                transport = paramiko.Transport(this_handler.request)
                host_key = paramiko.RSAKey(filename=self.host_key_path)
                transport.add_server_key(host_key)
                server_interface = SSHServerHandler(self)
                transport.start_server(server=server_interface)
                channel = transport.accept(20)
                if channel is None:
                    logging.warning("SSHServer: No channel accepted.")
                    return
                server_interface.event.wait(10)
                transport.close()

        self.server = ThreadedTCPServer((self.host, self.port), Handler)
        self.port = self.server.server_address[1]
        self.server_started.set()
        logging.info(f"SSH server listening on {self.host}:{self.port}")
        self.server.serve_forever()

    def start(self):
        logging.info("SSH server starting...")
        self.server_thread = threading.Thread(target=self._server_lifecycle)
        self.server_thread.daemon = True
        self.server_thread.start()
        logging.info("Waiting for server to start...")
        if not self.server_started.wait(timeout=10):
            raise RuntimeError("SSH server failed to start in time.")

        if self.startup_delay > 0:
            logging.info(f"Server started, delaying availability for {self.startup_delay}s")
        else:
            self.is_available.set()

        def lifecycle_manager():
            if self.startup_delay > 0:
                time.sleep(self.startup_delay)
                logging.info("Server is now available.")
                self.is_available.set()

            if self.unavailable_after > 0:
                time.sleep(self.unavailable_after)
                logging.info("Server is now unavailable.")
                self.is_available.clear()
                time.sleep(self.rebirth_delay)
                logging.info("Server is available again (rebirth).")
                self.is_available.set()

        lifecycle_thread = threading.Thread(target=lifecycle_manager)
        lifecycle_thread.daemon = True
        lifecycle_thread.start()
        logging.info(f"SSH server ready on port {self.port}.")

    def stop(self):
        if self.server:
            logging.info("SSH server shutting down...")
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        logging.info("SSH server stopped.")

    def add_file(self, filepath):
        with self.files_lock:
            logging.info(f"SSHServer: Adding file: {filepath}")
            self.files.add(filepath)

    def remove_file(self, filepath):
        with self.files_lock:
            logging.info(f"SSHServer: Removing file: {filepath}")
            self.files.discard(filepath)


@pytest.fixture(scope="function")
def robust_ssh_server():
    tempdir = tempfile.TemporaryDirectory()
    host = "127.0.0.1"
    port = 0

    private_key_path = os.path.join(tempdir.name, "id_rsa_test")
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(private_key_path)

    server = ParamikoSSHServer(host, port, private_key_path)
    yield server
    server.stop()
    tempdir.cleanup()


def test_waitforhostready_success_after5sec(
    pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, robust_ssh_server
):
    robust_ssh_server.start()
    private_key = Path(robust_ssh_server.host_key_path).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait",
    host="{robust_ssh_server.host}",
    port={robust_ssh_server.port},
    user="testuser",
    file_to_exist="/tmp/ready_file",
    private_key='''{private_key}''',
    timeout=30,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    def create_ready_file():
        time.sleep(5)
        robust_ssh_server.add_file("/tmp/ready_file")

    file_creator_thread = threading.Thread(target=create_ready_file)
    file_creator_thread.start()

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"
    file_creator_thread.join()


def test_waitforhostready_timeout(
    pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, robust_ssh_server
):
    robust_ssh_server.start()
    private_key = Path(robust_ssh_server.host_key_path).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait-timeout",
    host="{robust_ssh_server.host}",
    port={robust_ssh_server.port},
    user="testuser",
    file_to_exist="/tmp/never_exists",
    private_key='''{private_key}''',
    timeout=5,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    with pytest.raises(Exception) as excinfo:
        pulumi_stack.up(**pulumi_up_args)

    assert "Timeout waiting for host" in str(excinfo.value)


def test_waitforhostready_server_delayed_start(
    pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, robust_ssh_server
):
    robust_ssh_server.startup_delay = 5
    robust_ssh_server.start()
    private_key = Path(robust_ssh_server.host_key_path).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait-delayed-start",
    host="{robust_ssh_server.host}",
    port={robust_ssh_server.port},
    user="testuser",
    file_to_exist="/tmp/ready_file",
    private_key='''{private_key}''',
    timeout=30,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    robust_ssh_server.add_file("/tmp/ready_file")

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"


def test_waitforhostready_near_real_life(
    pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, robust_ssh_server
):
    robust_ssh_server.startup_delay = 5
    robust_ssh_server.unavailable_after = 5
    robust_ssh_server.rebirth_delay = 5
    robust_ssh_server.start()
    private_key = Path(robust_ssh_server.host_key_path).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait-near-real-life",
    host="{robust_ssh_server.host}",
    port={robust_ssh_server.port},
    user="testuser",
    file_to_exist="/tmp/ready_file",
    private_key='''{private_key}''',
    timeout=30,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    def create_ready_file():
        time.sleep(12)
        robust_ssh_server.add_file("/tmp/ready_file")

    file_creator_thread = threading.Thread(target=create_ready_file)
    file_creator_thread.start()

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"
    file_creator_thread.join()
