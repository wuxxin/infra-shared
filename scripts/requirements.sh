#!/usr/bin/env bash
set -eo pipefail
# set -x

usage() {
    local base_dir_short=$(basename $(dirname "$(dirname "$(readlink -e "$0")")"))
    cat <<EOF
Usage: $(basename $0)  --check | --list | --install | --install-aur | --containerfile

--check             - if all needed packages are installed exit 0, else 1
--list              - list all defined packages with comments
--install           - unconditionally install all needed normal packages
--install-aur       - unconditionally install all needed AUR packages
--containerfile     - update a Containerfile to include all needed packages


Usage of "--containerfile" needs two replacement lines in Containerfile for package hooks:
    - Hook for normal packages: "    pacman -Syu --noconfirm ... &&"
    - Hook for AUR packages   : "    yay -Sy --noconfirm ... &&"

Call With:
    cd ${base_dir_short}/Containerfile/provision-client &&
    cat Containerfile | ../../scripts/$(basename $0) --containerfile > Containerfile.new &&
    mv Containerfile.new Containerfile; cd $(pwd)

EOF
    exit 1
}

pkg_defines="
# # buildenv
# CHECK: pipenv openssl gpg gpgv age jose vault pulumi keymgr knotc atftp jq xz
# pipenv - virtual python environment management
python-pipenv
# openssl used for random, and hashid of cert
openssl
# gnupg used for gpg signed hash sums of os images
gnupg
# age - file based encryption with openssh authorized_keys and provision key
age
# jose - C-language implementation of Javascript Object Signing and Encryption
jose
# vault - used for ca root creation
vault
# pulumi - imperativ infrastructure delaration using python
pulumi
# knot - used for dns utilities
knot
# atftp - TFTP client (RFC1350)
atftp
# json manipulation
jq
# compression
xz

# # local build and update-system-config
# CHECK: salt-call
salt

# # mkdocs build
# CHECK: pango-view
# pango - library for layout and rendering of text - used for weasyprint by mkdocs-with-pdf
pango

# # aur build
# CHECK: go rustc cargo
go
rust

# # raspberry build
# CHECK: bsdtar mkfs.vfat udisksctl
# libarchive - Multi-format archive and compression library
libarchive
# dosfstools - DOS filesystem utilities
dosfstools
# udisks2 - Disk Management Service, version 2
udisks2

# # openwrt build
# CHECK: zip awk git openssl wget unzip python
zip gawk git openssl wget unzip python ncurses zlib gettext libxslt

# # esphome build
# CHECK: esptool.py
# esptool - utility to communicate with the ROM bootloader in Espressif ESP8266
esptool

"

aur_defines="
# # coreos build
# CHECK: butane coreos-installer
# butane - transpile butane into fedora coreos ignition files
butane
# coreos-installer - Installer for CoreOS disk images
coreos-installer

# SELinux module tools
# CHECK: semodule_package checkmodule
# KEY-OWNER: lautrbach@redhat.com
# PACKAGE-KEY: selinux B8682847764DF60DF52D992CBC3905F235179CF1 73de67c522ebe3ddca72cdd447f64c26aeda5d217316b9ca7ef2356cff2a9dd3
libsepol
semodule-utils
checkpolicy

# # esphome build
# # CHECK: esphome
# esphome - Solution for ESP8266/ESP32 projects with MQTT and Home Assistant
# esphome

"

gosu() { # $1=user , $@=param
    local user home
    user=$1
    shift
    if which gosu &>/dev/null; then
        gosu $user $@
    else
        home="$(getent passwd "$user" | cut -d: -f6)"
        setpriv --reuid=$user --regid=$user --init-groups env HOME=$home $@
    fi
}

package_key() {
    local name="$1" keyid="$2" hash="$3" target="/etc/pacman.d/$1-key.gpg"
    if test ! -e "$target"; then
        curl -sSL -o "${target}" "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${keyid}"
        echo "${hash} *${target}" | sha256sum -c
        pacman-key --add "${target}"
        pacman-key --lsign-key "${keyid}"
    fi
}

unsupported_os() { # $1=os_distributor
    cat <<EOF
Error: unsupported distribution ($1)"
    use the container image, or manually install the following:"
$pkg_list
$aur_list

EOF
    exit 1
}

main() {
    if test "$1" != "--check" -a "$1" != "--install" -a "$1" != "--install-aur" -a \
        "$1" != "--list" -a "$1" != "--containerfile"; then
        usage
    fi
    request=$1
    shift

    self_path=$(dirname "$(readlink -e "$0")")
    pkg_list=$(echo "$pkg_defines" | grep -v "^#" | grep -v "^ *$" | sort | uniq | tr "\n" " ")
    aur_list=$(echo "$aur_defines" | grep -v "^#" | grep -v "^ *$" | sort | uniq | tr "\n" " ")
    check_list=$(printf "%s\n%s" "$pkg_defines" "$aur_defines" |
        grep "^# CHECK:" | sed -r "s/# CHECK:(.*)/\1/g")
    os_distributor=$(lsb_release -i -s | tr '[:upper:]' '[:lower:]')

    if test "$request" = "--check"; then
        for cmd in $check_list; do
            if ! which $cmd &>/dev/null; then
                echo "Error: command not found: \"$cmd\"."
                echo "try \"sudo $0 --install\" or \"make install-requirements\""
                exit 1
            fi
        done

    elif test "$request" = "--install"; then
        if test "$os_distributor" = "arch"; then
            pacman -Syu --noconfirm $pkg_list
        elif test "$os_distributor" = "manjarolinux"; then
            pamac install --no-confirm --no-upgrade $pkg_list
        else
            unsupported_os $os_distributor
        fi

    elif test "$request" = "--install-aur"; then
        if test "$os_distributor" = "arch"; then
            if ! which yay &>/dev/null; then
                git clone https://aur.archlinux.org/yay.git
                cd yay
                makepkg --noconfirm
                doas -u root pacman --noconfirm -U *.pkg.tar.zst
                cd ..
                rm -rf yay
            fi
            yay -Sy --noconfirm --sudo doas $aur_list
        elif test "$os_distributor" = "manjarolinux"; then
            pamac install --no-confirm --no-upgrade $aur_list
        else
            unsupported_os $os_distributor
        fi

    elif test "$request" = "--list"; then
        printf '### PKG-START\n%s\n### PKG-END\n### AUR-START\n%s\n### AUR-END\n' \
            "$pkg_defines" "$aur_defines"

    elif test "$request" = "--containerfile"; then
        sed -r "s/^    pacman -Syu --noconfirm.+$/    pacman -Syu --noconfirm ${pkg_list} \&\& \\\\/g" |
            sed -r "s/^    yay -Sy --noconfirm.+$/    yay -Sy --noconfirm ${aur_list} \&\& \\\\/g"
    fi
}

main "$@"
