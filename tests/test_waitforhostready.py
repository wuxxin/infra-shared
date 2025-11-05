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

class SSHServer(paramiko.ServerInterface):
    def __init__(self, server_instance):
        self.server_instance = server_instance
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
        file_to_exist = command_str.split(" ")[-1]

        if file_to_exist in self.server_instance.files:
            channel.send_exit_status(0)
        else:
            channel.send_exit_status(1)

        self.event.set()
        return True

class MockSSHHandler(socketserver.BaseRequestHandler):
    def handle(self):
        transport = paramiko.Transport(self.request)
        transport.add_server_key(self.server.host_key)

        server = SSHServer(self.server)
        try:
            transport.start_server(server=server)
            server.event.wait(10)
        except Exception:
            pass
        finally:
            transport.close()


class MockSSHServer(socketserver.TCPServer):
    def __init__(self, server_address, RequestHandlerClass, host_key_path):
        super().__init__(server_address, RequestHandlerClass)
        self.host_key = paramiko.RSAKey(filename=host_key_path)
        self.files = []
        self.allow_reuse_address = True

@pytest.fixture(scope="function")
def ssh_keys(tmp_path):
    private_key_path = tmp_path / "id_rsa"
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(private_key_path))
    return str(private_key_path)

def test_waitforhostready_success(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, ssh_keys):
    host = "127.0.0.1"
    port = 2222

    server = MockSSHServer((host, port), MockSSHHandler, ssh_keys)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    time.sleep(1)  # Give the server a moment to start

    private_key = Path(ssh_keys).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait",
    host="{host}",
    port={port},
    user="testuser",
    file_to_exist="/tmp/ready_file",
    private_key='''{private_key}''',
    timeout=20
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    def create_ready_file():
        time.sleep(5)
        server.files.append("/tmp/ready_file")

    file_creator_thread = threading.Thread(target=create_ready_file)
    file_creator_thread.start()

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"

    file_creator_thread.join()
    server.shutdown()
    server.server_close()

def test_waitforhostready_timeout(pulumi_stack: Stack, pulumi_project_dir, pulumi_up_args, ssh_keys):
    host = "127.0.0.1"
    port = 2223

    server = MockSSHServer((host, port), MockSSHHandler, ssh_keys)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    time.sleep(1)

    private_key = Path(ssh_keys).read_text()

    program = f"""
import pulumi
from infra import tools

tools.WaitForHostReady(
    "test-wait-timeout",
    host="{host}",
    port={port},
    user="testuser",
    file_to_exist="/tmp/never_exists",
    private_key='''{private_key}''',
    timeout=3
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    with pytest.raises(Exception) as excinfo:
        pulumi_stack.up(**pulumi_up_args)

    assert "Timeout waiting for host" in str(excinfo.value)

    server.shutdown()
    server.server_close()
