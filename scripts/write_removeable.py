#!/usr/bin/env python
"""Write an image file to a removable storage device specified by a serial_number as user

- Uses UDisks2 via DBus to access the storage device without root access

"""

import argparse
import os
import sys
import shutil

import dbus
import tqdm


bus = dbus.SystemBus()


def get_drives():
    """Prints a list of storage devices (and if they are removeable)"""

    udisks_obj = bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
    udisks_obj_manager = dbus.Interface(
        udisks_obj, "org.freedesktop.DBus.ObjectManager"
    )
    managed_objects = udisks_obj_manager.GetManagedObjects()
    drives = []

    for path, interfaces in managed_objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            device_info = interfaces["org.freedesktop.UDisks2.Drive"]
            drive_data = {
                "path": os.path.basename(path),
                "serial": device_info["Serial"],
                "size": device_info["Size"],
                "removeable": "Removeable"
                if device_info["MediaRemovable"]
                else "Fixed",
                "present": device_info["TimeMediaDetected"],
            }
            partitions = []
            for part_path, part_interfaces in managed_objects.items():
                if "org.freedesktop.UDisks2.Block" in part_interfaces:
                    block_info = part_interfaces["org.freedesktop.UDisks2.Block"]
                    if "Drive" in block_info and block_info["Drive"] == path:
                        partition_data = {
                            "path": os.path.basename(part_path),
                            "id_uuid": block_info.get("IdUUID"),
                            "label": block_info.get("IdLabel"),
                            "size": block_info.get("Size"),
                        }
                        partitions.append(partition_data)
            drive_data["partitions"] = partitions
            drives.append(drive_data)
    return drives


def get_removeable_block_device(serial_number, disk_size):
    """Returns the whole disk block device path of an external attached device with specified serial and size(can be 0)"""

    udisks_obj = bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
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


def write_to_device(block_device_path, image_file, verbose=True):
    """Writes the image file to the specified device."""

    # Get the Block device object
    block_device_obj = bus.get_object("org.freedesktop.UDisks2", block_device_path)
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
                desc="Writing Image",
                initial=current_offset,
                disable=not verbose,
            ) as pbar:
                while True:
                    # read and write one data chunk
                    data = image_handle.read(chunk_size)
                    if not data:
                        break
                    pbar.update(len(data))
                    target_handle.write(data)


def patch_partitions(block_device_path, block_info, patches, verbose=True):
    """Write files on specific partitions after writing the image"""
    udisks_obj = bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
    udisks_obj_manager = dbus.Interface(
        udisks_obj, "org.freedesktop.DBus.ObjectManager"
    )
    managed_objects = udisks_obj_manager.GetManagedObjects()

    drive_path = block_info.get("Drive")
    if not drive_path:
        raise KeyError("Could not determine the drive path for patching.")

    for source_path, dest_with_partition in patches:
        partition_identifier, dest_on_partition = dest_with_partition.split("/", 1)
        partition_object_path = None

        for path, interfaces in managed_objects.items():
            if "org.freedesktop.UDisks2.Block" in interfaces:
                block_props = interfaces["org.freedesktop.UDisks2.Block"]
                if block_props.get("Drive") == drive_path:
                    if (
                        partition_identifier.startswith("@")
                        and block_props.get("IdUUID") == partition_identifier[1:]
                    ) or (
                        not partition_identifier.startswith("@")
                        and block_props.get("IdLabel") == partition_identifier
                    ):
                        partition_object_path = path
                        break
            if partition_object_path:
                break

        if not partition_object_path:
            if verbose:
                print(
                    f"Warning: Partition '{partition_identifier}' not found on the device for patching.",
                    file=sys.stderr,
                )
            continue

        filesystem_iface = None
        if (
            "org.freedesktop.UDisks2.Filesystem"
            in managed_objects[partition_object_path]
        ):
            filesystem_iface_obj = bus.get_object(
                "org.freedesktop.UDisks2", partition_object_path
            )
            filesystem_iface = dbus.Interface(
                filesystem_iface_obj, "org.freedesktop.UDisks2.Filesystem"
            )
        else:
            if verbose:
                print(
                    f"Warning: Partition '{partition_identifier}' does not have a mountable filesystem.",
                    file=sys.stderr,
                )
            continue

        try:
            # Mount the partition
            mount_options = {}
            mount_path = filesystem_iface.Mount(mount_options)
            if verbose:
                print(f"Partition '{partition_identifier}' mounted at {mount_path}")

            # Copy the file
            source_abs_path = os.path.abspath(source_path)
            dest_abs_path = os.path.join(mount_path, dest_on_partition)
            os.makedirs(os.path.dirname(dest_abs_path), exist_ok=True)
            shutil.copy2(source_abs_path, dest_abs_path)
            if verbose:
                print(f"Copied '{source_path}' to '{dest_with_partition}'")

        except dbus.exceptions.DBusException as e:
            print(
                f"Error patching partition '{partition_identifier}': {e}",
                file=sys.stderr,
            )
        finally:
            if filesystem_iface:
                try:
                    filesystem_iface.Unmount({})
                    if verbose:
                        print(f"Partition '{partition_identifier}' unmounted")
                except dbus.exceptions.DBusException as e:
                    print(
                        f"Error unmounting partition '{partition_identifier}': {e}",
                        file=sys.stderr,
                    )


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
    parser.add_argument(
        "--patch",
        action="append",
        nargs=2,
        metavar=("SOURCE", "DEST_ON_PARTITION"),
        help="""Patch a partition after writing the image.
Specify source path and destination path prepending the partition identifier
Use '@' prefix for UUID, e.g. 'u-boot.bin @7B77-95E7/boot/efi/u-boot.bin'
or filesystem label, eg. 'u-boot.bin EFI-SYSTEM/boot/efi/u-boot.bin'. """,
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--list", action="store_true", default=False, help="List all available drives"
    )
    group.add_argument(
        "--verbose", action="store_true", default=True, help="Enable verbose output"
    )
    group.add_argument(
        "--silent", action="store_false", dest="verbose", help="Disable verbose output"
    )

    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()

    elif args.list:
        drives = get_drives()
        if not drives:
            raise IndexError("ERROR: No drives found.")

        for drive in drives:
            print(
                f"Id: {drive['path']}"
                + f"  Serial: {drive['serial']}"
                + f"  Size: {drive['size']}"
                + f"  Type: {drive['removeable']}"
            )
            if drive["partitions"]:
                max_path = max(len(p["path"]) for p in drive["partitions"])
                max_uuid = max(len(str(p["id_uuid"])) for p in drive["partitions"])
                max_label = max(len(str(p["label"])) for p in drive["partitions"])
                max_size = max(len(str(p["size"])) for p in drive["partitions"])

                for partition in sorted(
                    drive["partitions"], key=lambda item: item["path"]
                ):
                    print(
                        f"  Device: {partition['path']:<{max_path}}  "
                        + f" Size: {partition['size']:<{max_size}}"
                        + f" Label: {partition.get('label', ''):<{max_label}}  "
                        + f" UUID: {partition.get('id_uuid', ''):<{max_uuid}}  "
                    )
            else:
                print("  no device partitions found.")

    elif args.dest_serial and args.source_image:
        try:
            block_device_path, block_info = get_removeable_block_device(
                args.dest_serial, args.dest_size
            )
            write_to_device(block_device_path, args.source_image, args.verbose)

            if args.patch:
                patch_partitions(
                    block_device_path, block_info, args.patch, args.verbose
                )

        except (KeyError, IndexError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
        print("Error: Invalid arguments.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
