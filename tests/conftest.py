import logging
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest
import paramiko
from pulumi.automation import create_or_select_stack, LocalWorkspaceOptions, Stack

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@pytest.fixture(scope="session")
def project_root():
    """Returns the root directory of the infra-shared project."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_project_dir(tmp_path_factory):
    """Creates a temporary directory for the test project and returns its Path."""
    return tmp_path_factory.mktemp("infra-test-project")


@pytest.fixture(scope="session")
def pulumi_project_dir(test_project_dir, project_root):
    """
    Initializes a new Pulumi project in the temporary directory by running
    the create_skeleton.sh script.
    """
    project_path = test_project_dir / "project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)

    # Run create_skeleton.sh
    create_skeleton_script = project_root / "scripts" / "create_skeleton.sh"
    cmd = [
        str(create_skeleton_script),
        "--project-dir",
        str(project_path),
        "--name-library",
        "infra",
        "--yes",
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # The skeleton script assumes it's a submodule, but for tests, we copy it.
    infra_path = project_path / "infra"
    shutil.copytree(
        project_root,
        infra_path,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "build"),
        dirs_exist_ok=True,
        symlinks=False,
    )

    # The Pulumi project needs access to the virtual environment of the main project.
    # We'll update Pulumi.yaml to point to it.
    pulumi_yaml_path = project_path / "Pulumi.yaml"
    pulumi_yaml_content = pulumi_yaml_path.read_text()

    # Calculate relative path to the main project's .venv
    main_venv_path = project_root / ".venv"
    if main_venv_path.exists():
        relative_venv_path = os.path.relpath(main_venv_path, project_path)
        updated_yaml_content = pulumi_yaml_content.replace(
            "virtualenv: .venv", f"virtualenv: {relative_venv_path}"
        )
        pulumi_yaml_path.write_text(updated_yaml_content)

    return project_path


@pytest.fixture(scope="function")
def pulumi_stack_config():
    """
    Default configuration for the Pulumi stack.
    This can be overridden in individual tests.
    """
    return {"stack_name": "sim", "add_conf": ""}


@pytest.fixture(scope="function")
def pulumi_up_args():
    return {
        "on_output": print,
        "on_error": print,
        "suppress_progress": True,
        "suppress_outputs": True,
        "log_to_std_err": True,
        "log_flow": True,
        "color": False,
        "log_verbosity": 1,
        "debug": False,
    }


@pytest.fixture(scope="function")
def pulumi_stack(pulumi_project_dir, pulumi_stack_config) -> Stack:
    """
    This fixture sets up a Pulumi stack for each test function.
    It creates the stack, yields it to the test, and then tears it down.
    """
    stack_name = pulumi_stack_config["stack_name"]
    add_conf = pulumi_stack_config["add_conf"]
    work_dir = str(pulumi_project_dir)

    # Pulumi state, stored within the test project dir
    pulumi_home = pulumi_project_dir / "state" / "pulumi"
    pulumi_home.mkdir(parents=True, exist_ok=True)

    # Copy config-template.yaml to Pulumi.sim.yaml for the 'sim' stack
    config_template = pulumi_project_dir / "config-template.yaml"
    stack_config_path = pulumi_project_dir / f"Pulumi.{stack_name}.yaml"
    shutil.copy(config_template, stack_config_path)

    # add custom conf and don't protect the CA root cert for tests
    with stack_config_path.open("a") as f:
        f.write(f"\n  ca_protect_rootcert: false\n{add_conf}\n")

    env_vars = {
        "PULUMI_CONFIG_PASSPHRASE": "test",
        "PULUMI_BACKEND_URL": f"file://{pulumi_home}",
    }

    print(f"Setting up Pulumi stack: {stack_name} in {work_dir}")
    stack = None
    try:
        opts = LocalWorkspaceOptions(work_dir=work_dir, env_vars=env_vars)
        stack = create_or_select_stack(stack_name=stack_name, work_dir=work_dir, opts=opts)
        print("Yielding stack to test.")
        yield stack

    finally:
        print(f"Tearing down Pulumi stack: {stack_name}...")
        if stack:
            stack.destroy(on_output=print)
            stack.workspace.remove_stack(stack_name)
        print("Teardown complete.")


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
        isready_file = command_str.split(" ")[-1]
        logging.info(f"SSHServer: Received exec request: {command_str}")

        with self.server.files_lock:
            file_found = isready_file in self.server.files

        if command_str.startswith("readlink -e"):
            # mimic readlink -e, output full virtual path if found, nothing if not.
            if file_found:
                logging.info(
                    f"SSHServer: File '{isready_file}' found. Returning exit status 0."
                )
                channel.send(f"{isready_file}\n")
                channel.send_exit_status(0)
            else:
                logging.info(
                    f"SSHServer: File '{isready_file}' not found. Returning exit status 1."
                )
                channel.send_exit_status(1)
        else:
            logging.info(
                f"SSHServer: Unknown exec request ({command_str}). Returning exit status 5."
            )
            channel.send_exit_status(5)

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
