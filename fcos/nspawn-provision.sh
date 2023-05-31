#!/usr/bin#/env bash
set -eo pipefail

resource="$1"
if test "$resource" = ""; then
    echo "ERROR: missing parameter resource"
    exit 1
fi

if test -e /etc/systemd/nspawn/${resource}.nspawn; then
    printf "provision start of machine ${resource} "
    systemd-nspawn --quiet --machine=${resource} --directory=/var/lib/machines/${resource}
    while ! machinectl list -a --no-legend | grep -q ^${resource}; do
        echo -n "."
        sleep 1
    done
    while ! machinectl show ${resource} | grep -q State=running; do
        echo -n "+"
        sleep 1
    done
    sleep 1
    echo " is running"

    if test -d etc/nspawn/build/${resource}; then
        echo "copy additional configuration and installation files to /tmp of machine"
        for f in /etc/nspawn/build/${resource}/*; do
            machinectl copy-to $(basename "$f") /etc/nspawn/build/${resource}/ /tmp/
        done

        if test -d /etc/nspawn/build/${resource}/nspawn.postinst.sh; then
            echo "execute nspawn.postinst.sh script in machine with stdin pipe"
            cat - | machinectl shell ${resource} /bin/sh -c \
                "/bin/chmod +x /tmp/nspawn.postinst.sh; /tmp/nspawn.postinst.sh --yes"
        else
            echo "Warning: build files found, but no nspawn.postinst.sh, skipping postinst step"
        fi
    fi

    printf "provision done, power off machine ${resource} "
    machinectl poweroff ${resource}
    while machinectl list -a --no-legend | grep -q ^${resource}; do
        echo -n "."
        sleep 1
    done
    echo " is stopped"
else
    printf "Error: missing /etc/systemd/nspawn/${resource}.nspawn"
    exit 1
fi

touch /var/local/flags/provision-${resource}.stamp
