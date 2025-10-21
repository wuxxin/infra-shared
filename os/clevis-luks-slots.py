#!/usr/bin/env python3
"""
Manages LUKS Clevis bindings based on a desired state provided as JSON lines

Expects an infra.os fedora coreos, with a podman container running fedora with saltstack installed.

see docs/butane.md for details of the detailed container setup, this script expects /usr to point to coreos /usr

"""

import sys
import os
import json
import subprocess
import argparse
import shlex
import re
from shutil import which


def run_command(cmd, check=True):
    """Executes a command and returns its stdout."""
    try:
        process = subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)
        return process.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command failed: {e.cmd}", file=sys.stderr)
        print(f"Stderr: {e.stderr.strip()}", file=sys.stderr)
        raise


def check_root():
    """Exits if the script is not run as root."""
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root.", file=sys.stderr)
        sys.exit(1)


def check_dependencies():
    """Checks for required command-line tools available under /usr because we are running in a container."""
    for cmd in [
        "clevis",
        "cryptsetup",
        "systemd-inhibit",
    ]:
        if not os.path.exists(cmd):
            print(f"ERROR: Required command '{cmd}' is not installed.", file=sys.stderr)
            sys.exit(1)


def get_luks_slot_info(device):
    """Returns a dictionary with total, used, and free LUKS slots."""
    dump = run_command(f"cryptsetup luksDump {shlex.quote(device)}")
    total = dump.count("Key Slot")
    enabled = dump.count("ENABLED")
    return {"total": total, "used": enabled, "free": total - enabled}


def get_current_bindings(device):
    """
    Parses `clevis luks list` output into a list of binding details.
    Returns: [{'slot': int, 'type': str, 'config': str}, ...]
    """
    try:
        output = run_command(f"clevis luks list -d {shlex.quote(device)}")
    except subprocess.CalledProcessError:
        return []

    bindings = []
    # Regex to capture: 1) slot number, 2) pin type, 3) JSON config
    pattern = re.compile(r"^(\d+):\s*(\w+)\s*'(.*)'$")
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            bindings.append(
                {"slot": int(match.group(1)), "type": match.group(2), "config": match.group(3)}
            )
    return bindings


def normalize_json(json_str):
    """Sorts keys in a JSON string for consistent comparison."""
    try:
        return json.dumps(json.loads(json_str), sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        return None


def compare_states(devices_config):
    """--is-equal-to mode: Checks if the single SSS binding matches."""
    overall_mismatch = False
    for config in devices_config:
        device = config["device"]
        desired_config = config["clevis"]
        print(f"--- Checking device: {device} ---")

        current_bindings = get_current_bindings(device)
        sss_bindings = [b for b in current_bindings if b["type"] == "sss"]

        if len(sss_bindings) != 1:
            print(f"MISMATCH: Expected 1 SSS binding, but found {len(sss_bindings)}.")
            overall_mismatch = True
            continue

        desired_norm = normalize_json(desired_config)
        current_norm = normalize_json(sss_bindings[0]["config"])

        if current_norm == desired_norm:
            print("OK: Current SSS configuration matches desired state.")
        else:
            print("MISMATCH: SSS configuration does not match desired state.")
            print(f"Desired: {desired_norm}")
            print(f"Current: {current_norm}")
            overall_mismatch = True

    sys.exit(1 if overall_mismatch else 0)


def _perform_rewrite(config):
    """Shared logic to replace all Clevis bindings with a new SSS binding."""
    device = config["device"]
    desired_config = config["clevis"]
    print(f"--- Rewriting Clevis bindings for device: {device} ---")

    # Safety check for free slots before we start
    if get_luks_slot_info(device)["free"] < 1:
        print(
            f"ERROR: No free LUKS slots on {device}. Cannot add new binding.", file=sys.stderr
        )
        return False

    # Add the new binding first (add-before-remove)
    print("Adding new SSS binding...")
    try:
        run_command(f"clevis luks bind -y -d {shlex.quote(device)} sss '{desired_config}'")
    except subprocess.CalledProcessError:
        print(
            f"ERROR: Failed to bind new SSS policy for {device}. Aborting rewrite.",
            file=sys.stderr,
        )
        return False

    # Get the slot of the binding we just added
    all_bindings = get_current_bindings(device)
    new_binding = next(
        (
            b
            for b in all_bindings
            if normalize_json(b["config"]) == normalize_json(desired_config)
        ),
        None,
    )

    if not new_binding:
        print(
            "ERROR: Could not find the newly created SSS binding. Aborting cleanup for safety.",
            file=sys.stderr,
        )
        return False

    # Remove all OTHER Clevis bindings
    print("Removing old Clevis bindings...")
    for old_binding in all_bindings:
        if old_binding["slot"] != new_binding["slot"]:
            print(f"  Unbinding old slot {old_binding['slot']}...")
            run_command(
                f"clevis luks unbind -d {shlex.quote(device)} -s {old_binding['slot']}"
            )

    print(f"Rewrite for {device} complete.")
    return True


def rewrite_from(devices_config):
    """--rewrite-from mode: Deletes all Clevis bindings and adds the new one."""
    for config in devices_config:
        _perform_rewrite(config)


def update_from(devices_config):
    """--update-from mode: Idempotently ensures the desired SSS binding is the only one."""
    for config in devices_config:
        device = config["device"]
        desired_config = config["clevis"]
        print(f"--- Updating device: {device} ---")

        current_bindings = get_current_bindings(device)
        sss_bindings = [b for b in current_bindings if b["type"] == "sss"]
        other_clevis_bindings = [b for b in current_bindings if b["type"] != "sss"]

        # Check if the state is already correct
        is_correct = False
        if len(sss_bindings) == 1 and not other_clevis_bindings:
            if normalize_json(sss_bindings[0]["config"]) == normalize_json(desired_config):
                is_correct = True

        if is_correct:
            print("OK: Configuration already matches desired state. No changes needed.")
        else:
            print("MISMATCH: Configuration differs. Performing update...")
            _perform_rewrite(config)


def rebind(devices_config):
    """--rebind mode: Regenerates the existing SSS binding using 'clevis luks regen'."""
    for config in devices_config:
        device = config["device"]
        # The desired_config from the JSON is not used by regen, but the device is.
        print(f"--- Regenerating SSS binding for device: {device} ---")

        current_bindings = get_current_bindings(device)
        sss_bindings = [b for b in current_bindings if b["type"] == "sss"]

        if not sss_bindings:
            print(
                f"WARNING: No existing SSS binding found on {device} to regenerate. Skipping.",
                file=sys.stderr,
            )
            continue

        if len(sss_bindings) > 1:
            print(
                f"WARNING: Multiple SSS bindings found on {device}. Regenerating all of them.",
                file=sys.stderr,
            )

        for binding in sss_bindings:
            slot = binding["slot"]
            print(f"  Regenerating binding in slot {slot}...")
            try:
                # Use -q for non-interactive mode
                run_command(f"clevis luks regen -q -d {shlex.quote(device)} -s {slot}")
            except subprocess.CalledProcessError:
                print(
                    f"ERROR: Failed to regenerate binding in slot {slot} for {device}.",
                    file=sys.stderr,
                )
                # Continue to the next binding/device
                continue

        print(f"Regeneration for {device} complete.")


def main():
    """Main function to parse arguments and dispatch to the correct mode."""

    parser = argparse.ArgumentParser(
        description="Manages LUKS Clevis bindings based on a desired JSON state. Has to be run as root.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)

    help_text = 'A JSON Lines string, e.g., \'{"device":"/dev/sda1", "clevis":"..."}\''
    group.add_argument("--is-equal-to", metavar="'<json_lines>'", help=help_text)
    group.add_argument("--rewrite-from", metavar="'<json_lines>'", help=help_text)
    group.add_argument("--update-from", metavar="'<json_lines>'", help=help_text)
    group.add_argument("--rebind", metavar="'<json_lines>'", help=help_text)

    args = parser.parse_args()

    # Determine which argument was used and get its value
    mode = None
    json_input = None
    if args.is_equal_to:
        mode, json_input = "is_equal_to", args.is_equal_to
    elif args.rewrite_from:
        mode, json_input = "rewrite_from", args.rewrite_from
    elif args.update_from:
        mode, json_input = "update_from", args.update_from
    elif args.rebind:
        mode, json_input = "rebind", args.rebind

    check_root()
    # check_dependencies()

    # Re-execute under systemd-inhibit if modifying the disk
    modifying_modes = ["rewrite_from", "update_from", "rebind"]
    if mode in modifying_modes and "_INHIBITED_RUN" not in os.environ:
        print("Acquiring systemd reboot inhibitor lock...")
        os.environ["_INHIBITED_RUN"] = "1"
        # sys.executable is the path to the current python interpreter
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Parse the JSON Lines input
    try:
        devices_config = [json.loads(line) for line in json_input.strip().splitlines()]
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON Lines string provided.", file=sys.stderr)
        sys.exit(1)

    # Dispatch to the correct function
    if mode == "is_equal_to":
        compare_states(devices_config)
    elif mode == "rewrite_from":
        rewrite_from(devices_config)
    elif mode == "update_from":
        update_from(devices_config)
    elif mode == "rebind":
        rebind(devices_config)


if __name__ == "__main__":
    main()
