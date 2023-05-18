#!/bin/bash

set -e

# Clean prior runs working files
rm -rf /tmp/packages
rm -rf /tmp/rpiboot

# Download the RPMs
echo Downloading RPMs
mkdir -p /tmp/packages
cd /tmp/packages
dnf install -y --downloadonly --release=$RELEASE --forcearch=aarch64 --destdir=/tmp/packages/ uboot-images-armv8 bcm283x-firmware bcm283x-overlays

# Extract some files
echo Extracting files from the RPMs
mkdir -p /tmp/rpiboot/boot/efi/
for rpm in /tmp/packages/*rpm; do rpm2cpio $rpm | cpio -id -D /tmp/rpiboot/; done

mv /tmp/rpiboot/usr/share/uboot/rpi_4/u-boot.bin /tmp/rpiboot/boot/efi/rpi4-u-boot.bin
mv /tmp/rpiboot/usr/share/uboot/rpi_3/u-boot.bin /tmp/rpiboot/boot/efi/rpi3-u-boot.bin

# ZIP them up into the output directory
echo Zipping files
cd /tmp/rpiboot/boot/efi
zip -qr /tmp/fcos-rpi-extras_$RELEASE.zip .
cp /tmp/fcos-rpi-extras_$RELEASE.zip /output
