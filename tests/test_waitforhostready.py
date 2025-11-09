import threading
import time
from pathlib import Path

import pytest
from pulumi.automation import Stack
from .utils import add_pulumi_program


def test_waitforhostready_success_after3sec(
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
    isready_cmd="readlink -e /tmp/ready_file",
    private_key='''{private_key}''',
    timeout=30,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    def create_ready_file():
        time.sleep(3)
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
    isready_cmd="readlink -e /tmp/never_exists",
    private_key='''{private_key}''',
    timeout=4,
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
    robust_ssh_server.startup_delay = 3
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
    isready_cmd="readlink -e /tmp/ready_file",
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
    robust_ssh_server.startup_delay = 3
    robust_ssh_server.unavailable_after = 3
    robust_ssh_server.rebirth_delay = 3
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
    isready_cmd="readlink -e /tmp/ready_file",
    private_key='''{private_key}''',
    timeout=30,
    connect_timeout=1,
    retry_delay=1,
)
"""
    add_pulumi_program(pulumi_project_dir, program)

    def create_ready_file():
        time.sleep(8)
        robust_ssh_server.add_file("/tmp/ready_file")

    file_creator_thread = threading.Thread(target=create_ready_file)
    file_creator_thread.start()

    up_result = pulumi_stack.up(**pulumi_up_args)
    assert up_result.summary.result == "succeeded"
    file_creator_thread.join()
