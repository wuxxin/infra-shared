import marimo

__generated_with = "0.8.0"
app = marimo.App(width="medium")


@app.cell
def __():
    import argparse
    import os
    import sys
    import textwrap

    import dbus
    import marimo as mo
    return argparse, dbus, mo, os, sys, textwrap


@app.cell
def __(mo):
    mo.md("""
    # Write image to removable storage device as User App

    Uses image from image_path to write to a removable storage device specified by serial_number.

    - Uses Udisks2 and DBus to access the storage devices as user interactive
    - Returns 0 for success, 1 for errors, and 2 for device not found or non-removable
    """)
    return


@app.cell
def __(device_name, os):
    def list_drives(udisks_interface):
        """Prints a list of storage devices (and if they are removeable)"""

        managed_objects = udisks_interface.GetManagedObjects()
        print("Pathname Removeable/Fixed Serial Size TimeMediaDetected")

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
                    return path, drive_info
        return None


    def get_block_device(drive_object_path, udisks_interface):
        managed_objects = udisks_interface.GetManagedObjects()

        for path, interfaces in managed_objects.items():
            if "org.freedesktop.UDisks2.Block" in interfaces:
                interface = interfaces["org.freedesktop.UDisks2.Block"]
                if interface["Drive"] == drive_object_path:
                    return interface
        return None


    def write_image_to_block_device(drive_object_path, image_file, udisks_interface):
        with open(image_file, "rb") as image:
            with open("/mnt/" + device_name, "wb") as destination:
                for chunk in iter(lambda: image.read(2**18), b""):
                    destination.write(chunk)
    return (
        get_block_device,
        get_removeable_drive,
        list_drives,
        write_image_to_block_device,
    )


@app.cell
def __(dbus):
    args = {"serial": "20220100016184", "imagepath": "state/"}

    bus = dbus.SystemBus()
    udisks = bus.get_object(
        "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2", introspect=False
    )
    udisks_manager = dbus.Interface(udisks, "org.freedesktop.DBus.ObjectManager")
    return args, bus, udisks, udisks_manager


@app.cell
def __(
    args,
    get_block_device,
    get_removeable_drive,
    list_drives,
    sys,
    udisks_manager,
):
    if not args:
        list_drives(udisks_manager)
    else:
        path, drive_interface = get_removeable_drive(args["serial"], udisks_manager)
        if drive_interface["Size"] == 0 or drive_interface["TimeMediaDetected"] == 0:
            print("ERROR: Size 0 or TimeMediaDetected 0", file=sys.stderr)
        else:
            block_interface = get_block_device(path, udisks_manager)
            if block_interface["Size"] == 0:
                print("ERROR: Size 0 or TimeMediaDetected 0", file=sys.stderr)
            else:
                print("Would write To Storage Device")
    return block_interface, drive_interface, path


if __name__ == "__main__":
    app.run()
