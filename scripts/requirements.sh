#!/usr/bin/env bash
set -eo pipefail
# set -x

usage() {
    local base_dir_short=$(basename $(dirname "$(dirname "$(readlink -e "$0")")"))
    cat <<EOF
Usage: $(basename $0)  --install [--dry-run] | --install-extra [--dry-run]
   or: $(basename $0)  --check | --list | --containerfile

--check         - if all needed packages are installed exit 0, else 1
--list          - list all defined packages with comments
--install       - unconditionally install all needed normal packages
    --dry-run     Show systempackages that would be installed, but dont install them
--install-extra - unconditionally install AUR (Arch/*),Python Pip or GO (Deb/*) pkgs
    --dry-run     Show AUR/Pip/Go packages that would be installed, but dont install them
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
check: lsb_release uv openssl gpg gpgv age jose vault pulumi keymgr knotc atftp jq xz act
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
# vault - used for ca root creation
sys-pkg: vault
go-deb: vault
# knot - used for dns utilities
sys: knot
# atftp - TFTP client (RFC1350)
sys: atftp
# json manipulation
sys: jq
# decompression for coreos images
sys-pkg: xz
sys-deb: xz-utils
# act - run your github actions locally
sys-pkg: act
go-deb: act
# saltstack is installed in the python environment, not as system package
# pulumi - imperativ infrastructure delaration using python
#   use git tag build with python and nodejs dynamic resource provider
aur: pulumi-git
go-deb: pulumi

# # extra packages build
check: go rustc cargo
sys-pkg: go
sys-deb: golang-go
sys-pkg: rust
sys-deb: rustc cargo

# # coreos build
check: butane coreos-installer
# butane - transpile butane into fedora coreos ignition files
aur: butane
go-deb: butane
# coreos-installer - Installer for CoreOS disk images
aur: coreos-installer
go-deb: coreos-installer

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

go_make() { # $1=bin_name $2=url $3=build_cmd $4=install_cmd
    local bin_name="$1" url="$2" build_cmd="$3" install_cmd="$4"
    local pwd=$(pwd) gomake_dir=$(mktemp -d -t gobuild_XXXXXXXXXX)
    echo "+ Building $bin_name from url: $url"
    mkdir -p $gomake_dir/bin $gomake_dir/$bin_name
    wget -qO- "$url" | tar -xz -C "$gomake_dir/$bin_name" --strip-components=1
    cd "$gomake_dir/$bin_name"
    echo "Build Command: $build_cmd"
    eval "$build_cmd" || true
    echo "Install Command: $install_cmd"
    eval "$install_cmd" || true
    cd "$pwd"
    rm -rf "$gomake_dir"
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
            elif [ "$type" = "go" ] && [ "$filter_value" = "deb" ] && [ "$OS_PKGFORMAT" = "deb" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    SYSTEM_PACKAGES_TO_INSTALL+=("golang-go")
                    GO_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
                fi
            elif [ "$type" = "go" ] && [ "$filter_value" = "pkg" ] && [ "$OS_PKGFORMAT" = "pkg" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    SYSTEM_PACKAGES_TO_INSTALL+=("go")
                    GO_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
                fi
            elif [ "$type" = "go" ] && [ "$filter_value" = "rpm" ] && [ "$OS_PKGFORMAT" = "rpm" ]; then
                if [ ${#current_packages_array[@]} -gt 0 ]; then
                    SYSTEM_PACKAGES_TO_INSTALL+=("go")
                    GO_PACKAGES_TO_INSTALL+=("${current_packages_array[@]}")
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
    deduplicate_array GO_PACKAGES_TO_INSTALL
    deduplicate_array CHECK_COMMANDS
    deduplicate_array ARCH_SYS_PACKAGES_FOR_CONTAINERFILE
    deduplicate_array ARCH_AUR_PACKAGES_FOR_CONTAINERFILE
}

main() {
    if test "$1" != "--check" -a "$1" != "--install" -a "$1" != "--install-extra" -a \
        "$1" != "--list" -a "$1" != "--containerfile"; then
        usage
    fi
    REQUEST=$1
    shift

    DRY_RUN=false
    if [ "$1" = "--dry-run" ]; then
        DRY_RUN=true
        shift
    fi

    parse_package_config
    self_path=$(dirname "$(readlink -e "$0")")

    if test "$REQUEST" = "--check"; then
        cat <<EOF
Detected distribution: $OS_DISTRONAME
Detected package format: $OS_PKGFORMAT
System packages: ${SYSTEM_PACKAGES_TO_INSTALL[@]}
AUR packages: ${AUR_PACKAGES_TO_INSTALL[@]}
PIP packages: ${PIP_PACKAGES_TO_INSTALL[@]}
Go packages: ${GO_PACKAGES_TO_INSTALL[@]}
Check commands: ${CHECK_COMMANDS[@]}
EOF

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
                    sudo "$pip_cmd" install "${PIP_PACKAGES_TO_INSTALL[@]}"
                else
                    unsupported_os "$OS_DISTRONAME for systemwide python Pip installation"
                fi
            fi

            if [ "$DRY_RUN" = "true" ]; then
                echo "Dry-run: Would attempt to install system wide Go packages: ${GO_PACKAGES_TO_INSTALL[@]}"
            else
                if [ ${#GO_PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
                    echo "Attempting to install system wide Go packages: ${GO_PACKAGES_TO_INSTALL[@]}"
                    if ! command -v go &>/dev/null; then
                        echo "Go command not found after system package installation. Cannot install Go packages." >&2
                    else
                        for pkg_name in "${GO_PACKAGES_TO_INSTALL[@]}"; do
                            if test "$pkg_name" = "act"; then
                                go_make "act" "https://github.com/nektos/act/archive/refs/tags/v0.2.77.tar.gz" "make build" "pwd; find dist"
                            elif test "$pkg_name" = "butane"; then
                                go_make "butane" "https://github.com/coreos/butane/archive/refs/tags/v0.23.0.tar.gz" \
                                    "go build -o bin/butane -ldflags '-w -X github.com/coreos/butane/internal/version.Raw=0.23.0' internal/main.go" \
                                    "pwd; find ."
                            elif test "$pkg_name" = "coreos-installer"; then
                                go_make "coreos-installer" "https://github.com/coreos/coreos-installer/archive/refs/tags/v0.24.0.tar.gz" \
                                    "cargo build --release" "pwd; find target"
                            elif test "$pkg_name" = "pulumi"; then
                                go_make "pulumi" "https://github.com/pulumi/pulumi/archive/refs/tags/v3.171.0.tar.gz" "make bin/pulumi" "pwd; find ."
                            elif test "$pkg_name" = "vault"; then
                                go_make "vault" "https://github.com/hashicorp/vault/archive/refs/tags/v1.19.4.tar.gz" "make bin" "pwd; find ."
                            else
                                echo "Error: package $pkg_name not supported for pkgformat $OS_PKGFORMAT and distribution $OS_DISTRONAME" >&2
                            fi
                        done
                    fi
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
GO_PACKAGES_TO_INSTALL=()
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
