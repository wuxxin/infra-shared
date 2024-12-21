#!/usr/bin/env python
"""Write an image file to a removable storage device specified by a serial_number as user

- Uses UDisks2 via DBus to access the storage devices without root access

"""

import argparse
import os
import sys

import dbus
import tqdm


def get_drives(udisks_obj):
    """Prints a list of storage devices (and if they are removeable)"""

    udisks_obj_manager = dbus.Interface(
        udisks_obj, "org.freedesktop.DBus.ObjectManager"
    )
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


def get_removeable_block_device(serial_number, disk_size, udisks_obj):
    """Returns the whole disk block device path of an external attached device with specified serial and size(can be 0)"""
    udisks_obj_manager = dbus.Interface(
        udisks_obj, "org.freedesktop.DBus.ObjectManager"
    )
    managed_objects = udisks_obj_manager.GetManagedObjects()
    drive_path = None
    drive_size = None

    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            drive_info = interfaces["org.freedesktop.UDisks2.Drive"]
            if drive_info["Serial"] == serial_number and drive_info["MediaRemovable"]:
                if disk_size != 0 and drive_info["Size"] != disk_size:
                    raise IndexError(
                        "disk size error of serial {}: Should: {} Actual: {}".format(
                            serial_number, disk_size, drive_info["Size"]
                        )
                    )
                drive_path = path
                drive_size = drive_info["Size"]
                break

    if not drive_path:
        raise KeyError("no removable disk with serial {} found".format(serial_number))

    potential_block_devices = []
    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Block" in interfaces:
            block_info = interfaces["org.freedesktop.UDisks2.Block"]
            if "Drive" in block_info and block_info["Drive"] == drive_path:
                potential_block_devices.append((path, block_info))

    if not potential_block_devices:
        raise KeyError(f"No block devices found for drive with serial {serial_number}")

    # Prioritize the block device representing the whole disk (matching size and offset 0)
    for path, block_info in potential_block_devices:
        block_size = block_info.get("Size")
        block_offset = block_info.get("Offset", 0)  # Offset might not always be present

        if block_size is not None and block_size == drive_size and block_offset == 0:
            return path, block_info

    raise KeyError(
        f"Could not find the whole disk block device for serial {serial_number}"
    )


def write_to_device(block_device_path, image_file, bus):
    """Writes the image file to the specified device."""

    # Get the Block device object
    block_device_obj = bus.get_object("org.freedesktop.UDisks2", block_device_path)
    # print(f"Block Device Object Path: {block_device_path}")
    block_device_iface = dbus.Interface(
        block_device_obj, "org.freedesktop.UDisks2.Block"
    )
    # open target block device exclusiv for writing
    target_device_dbus_fd = block_device_iface.OpenDevice(
        "w", dbus.Dictionary({"flags": os.O_EXCL | os.O_SYNC | os.O_CLOEXEC})
    )
    # take ownership of fd
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
                    # write chunk to device
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
    parser.add_argument(
        "--dest-size",
        help="optional Byte Size of the destination drive, as additional match criteria",
        type=int,
        default=0,
    )
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
        block_device_path, block_info = get_removeable_block_device(
            args.dest_serial, args.dest_size, udisks_obj
        )
        write_to_device(block_device_path, args.source_image, bus)

    else:
        parser.print_help()
        print("Error: Invalid arguments.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
