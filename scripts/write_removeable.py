#!/usr/bin/env python
"""Write image from image_path to removable storage device specified serial_number.

- Uses UDisks2 and DBus to access the storage devices as user
- Returns 0 for success, 1 for errors, and 2 for device not found or non-removable

"""

import argparse
import os
import sys

import dbus
import tqdm


def get_drives(udisk_obj):
    """Prints a list of storage devices (and if they are removeable)"""

    udisks_obj_manager = dbus.Interface(udisk_obj, "org.freedesktop.DBus.ObjectManager")
    managed_objects = udisks_obj_manager.GetManagedObjects()
    drives = []

    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            device_info = interfaces["org.freedesktop.UDisks2.Drive"]
            drives.append(
                {
                    "path": os.path.basename(path),
                    "serial": device_info["Serial"],
                    "size": device_info["Size"],
                    "removeable": "Removeable"
                    if device_info["MediaRemovable"]
                    else "Fixed",
                    "present": device_info["TimeMediaDetected"],
                }
            )
    return drives


def get_removeable_drive(serial_number, udisk_obj):
    """Returns UDisks2.Drive Interface of an external attached storage device with the specified serial number"""

    udisks_obj_manager = dbus.Interface(udisk_obj, "org.freedesktop.DBus.ObjectManager")
    managed_objects = udisks_obj_manager.GetManagedObjects()

    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            drive_info = interfaces["org.freedesktop.UDisks2.Drive"]
            if drive_info["Serial"] == serial_number and drive_info["MediaRemovable"]:
                return path, drive_info
    return None, None


def get_block_device_path(drive_object_path, udisk_obj):
    """Gets the block device object path."""

    udisks_obj_manager = dbus.Interface(udisk_obj, "org.freedesktop.DBus.ObjectManager")
    managed_objects = udisks_obj_manager.GetManagedObjects()

    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Block" in interfaces:
            interface = interfaces["org.freedesktop.UDisks2.Block"]
            if interface["Drive"] == drive_object_path:
                return path  # Return the path itself
    return None


def write_to_device(device_name, image_file, udisks_obj, bus):
    """Writes the image file to the specified device."""

    # Get the block device object for the target drive
    block_device_path = get_block_device_path(device_name, udisks_obj)
    if not block_device_path:
        raise Exception(f"Could not get block device path for {device_name}")
    block_device_obj = bus.get_object("org.freedesktop.UDisks2", block_device_path)
    block_device_iface = dbus.Interface(
        block_device_obj, "org.freedesktop.UDisks2.Block"
    )
    target_device_dbus_fd = block_device_iface.OpenDevice(
        "w", dbus.Dictionary({"flags": os.O_EXCL | os.O_SYNC | os.O_CLOEXEC})
    )
    fd = target_device_dbus_fd.take()

    with open(image_file, "rb") as image_handle:
        with os.fdopen(fd, "wb") as target_handle:
            filesize = os.fstat(image_handle.fileno()).st_size
            current_offset = 0
            chunk_size = pow(2, 20)

            with tqdm.tqdm(
                total=filesize,
                unit="B",
                unit_scale=True,
                desc="Writing",
                initial=current_offset,
            ) as pbar:
                while True:
                    data = image_handle.read(chunk_size)
                    if not data:
                        break
                    pbar.update(len(data))
                    target_handle.write(data)


def main():
    parser = argparse.ArgumentParser(
        description="Write image from to removable storage device specified by serial_number."
    )
    parser.add_argument("--dest-serial", help="Serial number of the destination drive")
    parser.add_argument("--source-image", help="Path to the source image file")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--list", action="store_true", default=False, help="List all available drives"
    )
    args = parser.parse_args()

    bus = dbus.SystemBus()
    udisks_obj = bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")

    if not any(vars(args).values()):
        parser.print_help()

    elif args.list:
        drives = get_drives(udisks_obj)
        if not drives:
            raise IndexError("ERROR: No drives found.")
        for drive in drives:
            print(
                f"path: {drive['path']}, Serial: {drive['serial']}, "
                + f"Size: {drive['size']}, Removeable: {drive['removeable']}"
            )

    elif args.dest_serial and args.source_image:
        device_name, drive_info = get_removeable_drive(args.dest_serial, udisks_obj)
        if not device_name:
            raise KeyError("serial {} not found".format(args.dest_serial))
        write_to_device(device_name, args.source_image, udisks_obj, bus)

    else:
        parser.print_help()
        print("Error: Invalid arguments.", file=sys.stderr)
        sys.exit(1)


"""
    # 1. Loop Setup on the image file
    udisks_manager_obj = bus.get_object(
        "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2/Manager"
    )
    udisks_manager = dbus.Interface(
        udisks_manager_obj, "org.freedesktop.UDisks2.Manager"
    )
    loop_device = udisks_manager.LoopSetup(
        image_handle.fileno(), dbus.Dictionary({"read-only": dbus.Boolean(True)})
    )
    # 4. Loop Remove
    udisks_manager.LoopRemove(loop_device, dbus.Dictionary({}))
"""

if __name__ == "__main__":
    main()
