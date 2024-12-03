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
    """Prints a list of storage devices (and if they are removeable)"""

    managed_objects = udisks_interface.GetManagedObjects()
    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            device_info = interfaces["org.freedesktop.UDisks2.Drive"]
            print(
                "{} {} {} {} {}".format(
                    os.path.basename(path),
                    "Removeable" if device_info["MediaRemovable"] else "Fixed",
                    device_info["Serial"],
                    device_info["Size"],  # 0 = if no medium inserted
                    device_info["TimeMediaDetected"],  # 0 if no medium inserted
                )
            )


def get_removeable_drive(serial_number, udisks_interface):
    """Returns UDisks2.Drive Interface of an external attached storage device with the specified serial number"""

    managed_objects = udisks_interface.GetManagedObjects()
    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            drive_info = interfaces["org.freedesktop.UDisks2.Drive"]
            if drive_info["Serial"] == serial_number and drive_info["MediaRemovable"]:
                drive_obj = bus.get_object("org.freedesktop.UDisks2", path)
                drive_iface = dbus.Interface(drive_obj, "org.freedesktop.UDisks2.Drive")
                return path, drive_info
    return None  # Device not found


def get_block_device(drive_object_path, udisks_interface):
    managed_objects = udisks_interface.GetManagedObjects()
    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Block" in interfaces:
            interface = interfaces["org.freedesktop.UDisks2.Block"]
            if interface["Drive"] == drive_object_path:
                return interface
    return None


def write_to_device(device_name, image_file, mount_interface):
    mount_options = [
        "fstype=iso9660"
        if os.path.splitext(image_file)[-1] == ".iso"
        else "fstype=ext4",
    ]
    mount_interface.Mount(mount_options)

    with open(image_file, "rb") as image:
        with open("/mnt/" + device_name, "wb") as destination:
            for chunk in iter(lambda: image.read(2**18), b""):
                destination.write(chunk)

    mount_interface.Unmount()


def main():
    parser = argparse.ArgumentParser()
    # parser.add_argument("image_path")
    # parser.add_argument("serial_number")
    args = parser.parse_args()

    bus = dbus.SystemBus()
    udisks = bus.get_object(
        "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2", introspect=False
    )
    udisks_manager = dbus.Interface(udisks, "org.freedesktop.DBus.ObjectManager")
    list_drives(udisks_manager)
    sys.exit()

    device_name = get_removeable_drive(args.serial_number)
    if not device_name:
        print("No serial number matching removeable device found", file=sys.stderr)
        exitcode = 2
    else:
        mount = bus.get_object("org.freedesktop.UDisks2", device_name, introspect=False)
        mount_interface = dbus.Interface(mount, "org.freedesktop.UDisks2.Mount")
        exitcode = write_to_device(device_name, args.image_path, mount_interface)
        if exitcode != 0:
            print("Error {} while writing occurred".format(exitcode), file=sys.stderr)

    sys.exit(exitcode)


if __name__ == "__main__":
    main()
