#!/usr/bin/env python
"""Write image from image_path to removable storage device specified serial_number.

- Uses Udisks2 and DBus to access the storage devices as user
- Returns 0 for success, 1 for errors, and 2 for device not found or non-removable

"""

import argparse
import os
import sys

import dbus


def list_drives(udisks_interface):
    """Prints a list of removeable devices"""

    drives = udisks_interface.GetDrives()
    for drive in drives:
        device_info = udisks_interface.GetDriveInfo(drive)
        print(
            "{} {} {}".format(
                udisks_interface.GetDriveByPath(drive),
                "Removeable" if device_info["type"] == "removeable" else "Fixed",
                device_info["serial"],
            )
        )


def get_removeable_drive(serial_number, udisks_interface):
    """Returns devicename of an external attached USB device with the specified serial number"""

    drives = udisks_interface.GetDrives()
    for drive in drives:
        device_info = udisks_interface.GetDriveInfo(drive)
        if (
            device_info["serial"] == serial_number
            and device_info["type"] == "removable"
        ):
            device_name = udisks_interface.GetDriveByPath(drive)
            return device_name

    return None  # Device not found


def write_to_device(device, image_file, mount_interface):
    if not device:
        print("No serial number matching USB device found or device not removeable")
        return 2

    mount_options = [
        "fstype=iso9660"
        if os.path.splitext(image_file)[-1] == ".iso"
        else "fstype=ext4",
    ]
    mount_interface.Mount(mount_options)

    with open(image_file, "rb") as image:
        with open("/mnt/" + device, "wb") as destination:
            for chunk in iter(lambda: image.read(4096), b""):
                destination.write(chunk)

    mount_interface.Unmount()
    return 0


def main():
    parser = argparse.ArgumentParser()
    # parser.add_argument("image_path")
    # parser.add_argument("serial_number")
    args = parser.parse_args()

    bus = dbus.SystemBus()
    udisks = bus.get_object("org.freedesktop.udisks2", "/", introspect=False)
    udisks_interface = dbus.Interface(udisks, "org.freedesktop.udisks2")

    list_drives(udisks_interface)
    sys.exit()

    device = get_removeable_drive(args.serial_number)
    if not device:
        result = 2
        print("Device not found", file=sys.stderr)
    else:
        mount = bus.get_object("org.freedesktop.udisks2", device, introspect=False)
        mount_interface = dbus.Interface(mount, "org.freedesktop.udisks2.Mount")
        result = write_to_device(device, args.image_path, mount_interface)
        if result != 0:
            print("Error {} occurred".format(result), file=sys.stderr)

    sys.exit(result)


if __name__ == "__main__":
    main()
