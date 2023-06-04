#!/usr/bin/env bash
set -eo pipefail

repl_url() {
    echo "$1" | sed -r "s/\$\{VERSION}/${VERSION}/g" | sed -r "s/\$\{ARCH}/${ARCH}/g"
}

if test "$1" != "--yes"; then
    echo "ERROR: missing --yes parameter"
    echo "call with $0 --yes version file_url local_file hash_url sha256sum flag_file architecture"
    exit 1
fi

VERSION="$2"
FILE_URL="$3"
LOCAL_FILE="$4"
HASH_URL="$5"
SHA256SUM="$6"
FLAG_FILE="$7"
ARCH="$8"

if test "$HASH_URL" = "" -a "$SHA256SUM" = ""; then
    echo "ERROR: either SHA256SUM or HASH_URL must be set"
    exit 1
fi

BASE_FILE="$(basename $LOCAL_FILE)"
VER_INUSE="$(if test -e "$FLAG_FILE"; then cat "$FLAG_FILE"; else echo "0"; fi)"
VER_GT="$(printf "%s\n%s\n" "$VERSION" "$VER_INUSE" | sort -Vr | head -n1)"

if test "$VER_INUSE" != "$VERSION" -o ! -e "$LOCAL_FILE"; then
    if test "$VER_GT" = "$VERSION" -o ! -e "$LOCAL_FILE"; then
        TEMP_DIR="$(mktemp -d)" && trap "rm -rf $TEMP_DIR" EXIT
        curl -sSL -o "$TEMP_DIR/$BASE_FILE" "$(repl_url "$FILE_URL")"

        if test "$HASH_URL" != ""; then
            curl -sSL -o "$TEMP_DIR/${BASE_FILE}.hash" "$(repl_url "$HASH_URL")"
            pushd "$TEMP_DIR"
            cat "$TEMP_DIR/${BASE_FILE}.hash" |
                sed -r "s/^([^ ]+) +(.+)$/\1 *${BASE_FILE}/g" | sha256sum -c
            popd
        fi

        if test "$SHA256SUM" != ""; then
            pushd "$TEMP_DIR"
            printf "%s *%s" "$SHA256SUM" "$BASE_FILE" | sha256sum -c
            popd
        fi
    fi

    mv "$TEMP_DIR/$BASE_FILE" "$LOCAL_FILE"
    chmod +x "$LOCAL_FILE"
    echo "$VERSION" >"$FLAG_FILE"
fi
