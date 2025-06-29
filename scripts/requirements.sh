#!/usr/bin/env bash
set -eo pipefail
# set -x

usage() {
    local base_dir_short=$(basename $(dirname "$(dirname "$(readlink -e "$0")")"))
    cat <<EOF
Usage: $(basename $0)  --install [--dry-run] | --install-extra [--user] [--dry-run]
   or: $(basename $0)  --check [--verbose] | --list | --containerfile

--check         - if all needed packages are installed exit 0, else 1
    --verbose     Show additional package information
--list          - list all defined packages with comments
--install       - unconditionally install all needed normal packages
    --dry-run     Show systempackages that would be installed, but dont install them
--install-extra - unconditionally install AUR (Arch/*),Python Pip (Deb/*)or Custom (*) pkgs
    --user        copy custom build packages to ~/.local/bin instead of /usr/local/bin
    --dry-run     Show AUR/Pip/Custom packages that would be installed, but dont install them
--containerfile - update a Containerfile to include all needed packages

    Usage of "--containerfile" needs two replacement lines in Containerfile for package hooks:
        - Hook for normal packages: "    pacman -Syu --noconfirm ... &&"
        - Hook for AUR packages   : "    yay -Sy --noconfirm ... &&"

    Call With:
        cd ${base_dir_short}/Containerfile/provision-client &&
            cat Containerfile |
                ../../scripts/$(basename $0) --containerfile > Containerfile.new &&
            mv Containerfile.new Containerfile; cd $(pwd)

EOF
    exit 1
}

PKG_CONFIG="
# # buildenv
check: lsb_release uv openssl gpg gpgv age jose keymgr knotc knsupdate atftp jq xz zstd

# lsb-release - LSB version query program
sys: lsb-release
# uv - extremely fast Python package installer and resolver written in Rust
sys-arch: uv
pip-deb: uv
# openssl used for random, and hashid of cert
sys: openssl
# gnupg used for gpg signed hash sums of os images
sys: gnupg
# age - file based encryption with openssh authorized_keys and provision key
sys: age
# jose - C-language implementation of Javascript Object Signing and Encryption
sys: jose
# knot - used for dns utilities
sys: knot
sys-deb: knot-dnsutils
# atftp - TFTP client (RFC1350)
sys: atftp
# json manipulation
sys: jq
# decompression of coreos images
sys-pkg: xz
sys-deb: xz-utils
# decompression of zstd files
sys: zstd

# # extra and custom packages buildenv
check: go rustc cargo
sys-pkg: go
sys-deb: golang-go
sys-pkg: rust
sys-deb: rustc cargo
sys-deb: python3-dev

# python environment
sys-deb: pkg-config libdbus-1-dev libglib2.0-dev
# saltstack is installed in the python environment, not as system package

# # coreos build
check: butane coreos-installer
# butane - transpile butane into fedora coreos ignition files
aur: butane
# build dependencies for butane
sys-deb: libzstd-dev
custom-deb: butane
# coreos-installer - Installer for CoreOS disk images
aur: coreos-installer
custom-deb: coreos-installer

# # pulumi - imperativ infrastructure delaration using python
check: pulumi
# aur: use git tag build with python and nodejs dynamic resource provider
aur: pulumi-git
custom-deb: pulumi

# vault - used for ca root creation
check: vault
sys-pkg: vault
custom-deb: vault

# act - run your github actions locally
check: act
sys-pkg: act
custom-deb: act

# # mkdocs build
check: pango-view
# pango - library for layout and rendering of text - used for weasyprint by mkdocs-with-pdf
sys-pkg: pango
sys-deb: pango1.0-tools

# # raspberry build
check: bsdtar mkfs.vfat udisksctl
# libarchive - Multi-format archive and compression library
sys-pkg: libarchive
sys-deb: libarchive-tools
# dosfstools - DOS filesystem utilities
sys: dosfstools
# udisks2 - Disk Management Service, version 2
sys: udisks2

# # openwrt build
check: zip awk git openssl wget unzip python
sys: zip gawk git openssl wget unzip
sys-pkg: python
sys-deb: python3 python3-pip
sys-pkg: ncurses
sys-deb: libncurses6
sys-pkg: zlib
sys-deb: zlib1g
sys-pkg: gettext
sys-deb: gettext-base
sys-pkg: libxslt
sys-deb: libxslt1.1

# # esphome build
# esphome - Solution for ESP8266/ESP32 projects with MQTT and Home Assistant
# check: esphome esptool.py
sys-pkg: esphome esptool
# pip-deb: esphome esptool

# # SELinux module tools
check: semodule_package checkmodule
# KEY-OWNER: lautrbach@redhat.com
# PACKAGE-KEY: selinux B8682847764DF60DF52D992CBC3905F235179CF1 73de67c522ebe3ddca72cdd447f64c26aeda5d217316b9ca7ef2356cff2a9dd3
aur: libsepol semodule-utils checkpolicy
sys-deb: semodule-utils checkpolicy

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

package_key() { # $1=name $2=keyid $3=hash
    local name="$1" keyid="$2" hash="$3" target="/etc/pacman.d/$1-key.gpg"
    if test ! -e "$target"; then
        curl -sSL -o "${target}" "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${keyid}"
        echo "${hash} *${target}" | sha256sum -c
        pacman-key --add "${target}"
        pacman-key --lsign-key "${keyid}"
    fi
}

unsupported_os() { # $1=message_context
    echo "Error: Unsupported installation ($1)"
    exit 1
}

deduplicate_array() { # $1=array
    declare -n arr_ref="$1"
    if [ ${#arr_ref[@]} -gt 0 ]; then
        local unique_pkgs_str=$(echo "${arr_ref[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/ $//')
        arr_ref=($(echo "$unique_pkgs_str"))
    fi
}

parse_package_config() {
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Remove comments
        line_no_comments="${line%%#*}"
        # Trim whitespace
        trimmed_line="$(echo -e "${line_no_comments}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        if [ -z "$trimmed_line" ]; then continue; fi

        # Parse type_and_filter and packages_string
        type_and_filter="${trimmed_line%%:*}"
        packages_string="${trimmed_line#*: }" # Also trim leading space after colon

        # Split type_and_filter into type and filter_value
        type="${type_and_filter%%-*}"
        filter_value="${type_and_filter#*-}"
        if [ "$type" = "$filter_value" ]; then filter_value=""; fi

        applies=false
        if [ -z "$filter_value" ]; then
            applies=true
        elif [[ "$OS_PKGFORMAT" == "$filter_value" ]]; then
            applies=true
        elif [[ "$OS_DISTRONAME" == "$filter_value" ]]; then
            applies=true
        fi

        if $applies; then
            read -r -a current_packages_array <<<"$packages_string"
            if [ "$type" = "sys" ]; then
                SYSTEM_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
            elif [ "$type" = "aur" ] && [ "$OS_PKGFORMAT" = "pkg" ]; then
                AUR_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
            elif [ "$type" = "pip" ] && [ "$OS_PKGFORMAT" = "deb" ]; then
                PIP_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
            elif [ "$type" = "custom" ] && [ "$filter_value" = "deb" ] && [ "$OS_PKGFORMAT" = "deb" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    CUSTOM_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
                fi
            elif [ "$type" = "custom" ] && [ "$filter_value" = "pkg" ] && [ "$OS_PKGFORMAT" = "pkg" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    CUSTOM_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
                fi
            elif [ "$type" = "custom" ] && [ "$filter_value" = "rpm" ] && [ "$OS_PKGFORMAT" = "rpm" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    CUSTOM_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
                fi
            elif [ "$type" = "check" ]; then
                CHECK_COMMANDS+=("${current_packages_array[@]}")
            fi
        fi

        # Logic for ARCH_..._FOR_CONTAINERFILE arrays
        read -r -a current_packages_array_for_containerfile <<<"$packages_string"
        if [ "$type" = "sys" ]; then
            if [ -z "$filter_value" ] || [ "$filter_value" = "pkg" ] || [ "$filter_value" = "arch" ]; then
                ARCH_SYS_PACKAGES_FOR_CONTAINERFILE+=("${current_packages_array_for_containerfile[@]}")
            fi
        elif [ "$type" = "aur" ]; then
            if [ -z "$filter_value" ] || [ "$filter_value" = "pkg" ] || [ "$filter_value" = "arch" ]; then
                ARCH_AUR_PACKAGES_FOR_CONTAINERFILE+=("${current_packages_array_for_containerfile[@]}")
            fi
        fi

    done <<<"$PKG_CONFIG"

    deduplicate_array SYSTEM_PACKAGES_TO_INSTALL
    deduplicate_array AUR_PACKAGES_TO_INSTALL
    deduplicate_array PIP_PACKAGES_TO_INSTALL
    deduplicate_array CUSTOM_PACKAGES_TO_INSTALL
    deduplicate_array CHECK_COMMANDS
    deduplicate_array ARCH_SYS_PACKAGES_FOR_CONTAINERFILE
    deduplicate_array ARCH_AUR_PACKAGES_FOR_CONTAINERFILE
}

main() {
    VERBOSE=false
    DRY_RUN=false
    INSTALL_USER=false

    if test "$1" != "--check" -a "$1" != "--install" -a "$1" != "--install-extra" -a \
        "$1" != "--list" -a "$1" != "--containerfile"; then
        usage
    fi
    REQUEST=$1
    shift

    if test "$REQUEST" = "--check" -a "$1" = "--verbose"; then
        VERBOSE=true
        shift
    fi
    if test "$REQUEST" = "--install" -o "$REQUEST" = "--install-extra"; then
        if [ "$1" = "--user" ]; then
            INSTALL_USER=true
            shift
        fi
        if [ "$1" = "--dry-run" ]; then
            DRY_RUN=true
            shift
        fi
    fi

    parse_package_config
    self_path=$(dirname "$(readlink -e "$0")")

    if test "$REQUEST" = "--check"; then
        if test "$VERBOSE" = "true"; then
            cat <<EOF
Detected distribution: $OS_DISTRONAME
Detected package format: $OS_PKGFORMAT
System packages: ${SYSTEM_PACKAGES_TO_INSTALL[@]}
AUR packages: ${AUR_PACKAGES_TO_INSTALL[@]}
PIP packages: ${PIP_PACKAGES_TO_INSTALL[@]}
Custom packages: ${CUSTOM_PACKAGES_TO_INSTALL[@]}
Check commands: ${CHECK_COMMANDS[@]}
EOF
        fi
        all_found="true"
        for cmd in "${CHECK_COMMANDS[@]}"; do
            if ! command -v "$cmd" &>/dev/null; then
                echo "Error: command not found: \"$cmd\"."
                all_found="false"
            fi
        done
        if test "$all_found" = "true"; then
            echo "All dependencies installed."
        else
            echo "Error: Some dependencies failed."
            exit 1
        fi

    elif test "$REQUEST" = "--install"; then
        if [ "$DRY_RUN" = "true" ]; then
            echo "Dry-run: Would install system packages: ${SYSTEM_PACKAGES_TO_INSTALL[@]}"
        else
            if [ ${#SYSTEM_PACKAGES_TO_INSTALL[@]} -eq 0 ]; then
                echo "No system packages to install for this distribution based on the current configuration."
            else
                echo "Attempting to install system packages: ${SYSTEM_PACKAGES_TO_INSTALL[@]}"
                if [ "$OS_PKGFORMAT" = "pkg" ]; then
                    if [ "$OS_DISTRONAME" = "arch" ]; then
                        sudo pacman -Syu --noconfirm --needed "${SYSTEM_PACKAGES_TO_INSTALL[@]}"
                    elif [ "$OS_DISTRONAME" = "manjarolinux" ]; then
                        sudo pamac install --no-confirm --no-upgrade "${SYSTEM_PACKAGES_TO_INSTALL[@]}"
                    else
                        unsupported_os "$OS_DISTRONAME for archlinux package format"
                    fi
                elif [ "$OS_PKGFORMAT" = "deb" ]; then
                    sudo apt-get update
                    sudo apt-get install -y "${SYSTEM_PACKAGES_TO_INSTALL[@]}"
                elif [ "$OS_PKGFORMAT" = "rpm" ]; then
                    sudo dnf install -y "${SYSTEM_PACKAGES_TO_INSTALL[@]}"
                else
                    unsupported_os "$OS_DISTRONAME for $OS_PKGFORMAT package format"
                fi
            fi
        fi

    elif test "$REQUEST" = "--install-extra"; then
        if [ "$OS_PKGFORMAT" = "pkg" ]; then
            if [ "$DRY_RUN" = "true" ]; then
                echo "Dry-run: Would attempt to install AUR packages: ${AUR_PACKAGES_TO_INSTALL[@]}"
            else
                if [ ${#AUR_PACKAGES_TO_INSTALL[@]} -eq 0 ]; then
                    echo "No AUR packages to install for this PKG-based distribution."
                fi
                echo "Attempting to install AUR packages: ${AUR_PACKAGES_TO_INSTALL[@]}"
                if [ "$OS_DISTRONAME" = "arch" ]; then
                    if ! command -v yay &>/dev/null; then
                        echo "yay is not installed. Attempting to install yay..."
                        TEMP_DIR=$(mktemp -d)
                        current_dir=$(pwd)
                        git clone https://aur.archlinux.org/yay.git "$TEMP_DIR/yay"
                        cd "$TEMP_DIR/yay"
                        makepkg --noconfirm -si
                        cd "$current_dir"
                        rm -rf "$TEMP_DIR"
                        if ! command -v yay &>/dev/null; then
                            echo "Failed to install yay. Please install it manually."
                            exit 1
                        fi
                    fi
                    yay -Sy --noconfirm --sudo doas --needed "${AUR_PACKAGES_TO_INSTALL[@]}"
                elif [ "$OS_DISTRONAME" = "manjarolinux" ]; then
                    sudo pamac build --no-confirm "${AUR_PACKAGES_TO_INSTALL[@]}"
                else
                    unsupported_os "$OS_DISTRONAME for archlinux AUR package installation"
                fi
            fi

        elif [ "$OS_PKGFORMAT" = "deb" ]; then
            if [ "$DRY_RUN" = "true" ]; then
                echo "Dry-run: Would attempt to install system wide Pip packages: ${PIP_PACKAGES_TO_INSTALL[@]}"
            else
                if [ ${#PIP_PACKAGES_TO_INSTALL[@]} -eq 0 ]; then
                    echo "No Pip packages to install for this DEB-based distribution."
                fi
                if [ "$OS_DISTRONAME" = "debian" ] || [ "$OS_DISTRONAME" = "ubuntu" ]; then
                    echo "Attempting to install system wide Pip packages: ${PIP_PACKAGES_TO_INSTALL[@]}"
                    pip_cmd="pip"
                    if command -v pip3 &>/dev/null; then pip_cmd="pip3"; fi
                    sudo "$pip_cmd" install --break-system-packages "${PIP_PACKAGES_TO_INSTALL[@]}"
                else
                    unsupported_os "$OS_DISTRONAME for systemwide python Pip installation"
                fi
            fi

            if [ "$DRY_RUN" = "true" ]; then
                echo "Dry-run: Would attempt to install system/user wide custom packages: ${CUSTOM_PACKAGES_TO_INSTALL[@]}"
            else
                if [ ${#CUSTOM_PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
                    echo "Attempting to install system/user wide custom packages: ${CUSTOM_PACKAGES_TO_INSTALL[@]}"
                    make_dir=$(mktemp -d -t build_XXXXXXXXXX)
                    dir_prefix="/usr/local/bin"
                    call_prefix="sudo"
                    if test "$INSTALL_USER" = "true"; then
                        dir_prefix="$HOME/.local/bin"
                        call_prefix=""
                        mkdir -p "$dir_prefix"
                    fi

                    for pkg_name in "${CUSTOM_PACKAGES_TO_INSTALL[@]}"; do
                        echo "Attempting to install system/user wide custom package $pkg_name"

                        if test -e "$dir_prefix/$pkg_name"; then
                            echo "Skipping install of already existing $dir_prefix/$pkg_name"
                        else
                            if test "$pkg_name" = "act"; then
                                curl -sSL -o $make_dir/act.tar.gz https://github.com/nektos/act/releases/download/v0.2.77/act_Linux_x86_64.tar.gz
                                tar -xz -C $make_dir -f $make_dir/act.tar.gz act
                                $call_prefix install $make_dir/act $dir_prefix/act
                            elif test "$pkg_name" = "butane"; then
                                curl -sSL -o $make_dir/butane https://github.com/coreos/butane/releases/download/v0.23.0/butane-x86_64-unknown-linux-gnu
                                $call_prefix install $make_dir/butane $dir_prefix/butane
                            elif test "$pkg_name" = "pulumi"; then
                                curl -sSL -o $make_dir/pulumi.tar.gz https://github.com/pulumi/pulumi/releases/download/v3.171.0/pulumi-v3.171.0-linux-x64.tar.gz
                                tar -xz -C $make_dir -f $make_dir/pulumi.tar.gz pulumi
                                for i in $(find $make_dir/pulumi -type f); do
                                    $call_prefix install $i $dir_prefix/$(basename $i)
                                done
                            elif test "$pkg_name" = "coreos-installer"; then
                                # XXX ubuntu 24.04: coreos-installer 0.24.0 requires rustc 1.84.1 or newer, active rustc 1.75.0
                                curl -sSL -o $make_dir/coreos-installer.tar.gz \
                                    "https://github.com/coreos/coreos-installer/archive/refs/tags/v0.23.0.tar.gz"
                                curl -sSL -o $make_dir/coreos-installer-vendor.tar.gz \
                                    "https://github.com/coreos/coreos-installer/releases/download/v0.23.0/coreos-installer-0.23.0-vendor.tar.gz"
                                mkdir -p $make_dir/coreos-installer
                                tar -xz -C $make_dir/coreos-installer -f $make_dir/coreos-installer.tar.gz --strip-components=1
                                tar -xz -C $make_dir/coreos-installer -f $make_dir/coreos-installer-vendor.tar.gz
                                pwd=$(pwd) && cd $make_dir/coreos-installer && cargo build --release
                                cd $pwd
                                $call_prefix install $make_dir/coreos-installer/target/release/coreos-installer $dir_prefix/coreos-installer
                            elif test "$pkg_name" = "vault" -a "$OS_PKGFORMAT" = "deb"; then
                                wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
                                echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
                                sudo apt-get update && sudo apt-get install vault --yes
                            else
                                echo "Error: package $pkg_name not supported for pkgformat $OS_PKGFORMAT and distribution $OS_DISTRONAME" >&2
                            fi
                        fi
                    done
                    rm -r $make_dir
                fi
            fi
        fi

    elif test "$REQUEST" = "--list"; then
        printf "%s\n" "$PKG_CONFIG"

    elif test "$REQUEST" = "--containerfile"; then
        pacman_cmd_part="pacman -Syu --noconfirm ${ARCH_SYS_PACKAGES_FOR_CONTAINERFILE[*]} \&\& \\\\"
        yay_cmd_part="yay -Sy --noconfirm ${ARCH_AUR_PACKAGES_FOR_CONTAINERFILE[*]} \&\& \\\\"
        # XXX ensure the leading spaces for Containerfile format are present
        cat - |
            sed -r "s|^    pacman -Syu --noconfirm.*$|    $pacman_cmd_part|g" |
            sed -r "s|^    yay -Sy --noconfirm.*$|    $yay_cmd_part|g"
    fi
}

#
# ### main

SYSTEM_PACKAGES_TO_INSTALL=()
AUR_PACKAGES_TO_INSTALL=()
PIP_PACKAGES_TO_INSTALL=()
CUSTOM_PACKAGES_TO_INSTALL=()
CHECK_COMMANDS=()
ARCH_SYS_PACKAGES_FOR_CONTAINERFILE=()
ARCH_AUR_PACKAGES_FOR_CONTAINERFILE=()

OS_DISTRONAME=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
OS_PKGFORMAT='unknown'
if command -v pacman &>/dev/null; then
    OS_PKGFORMAT='pkg'
elif command -v apt-get &>/dev/null; then
    OS_PKGFORMAT='deb'
elif command -v dnf &>/dev/null || command -v yum &>/dev/null; then
    OS_PKGFORMAT='rpm'
fi

main "$@"
