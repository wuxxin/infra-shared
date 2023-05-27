#!/usr/bin#/env bash
set -eo pipefail

resource="$1"

if test -d /etc/nspawn/build/${resource}; then
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

    echo "copy additional configuration and installation files"
    machinectl copy-to ${resource} /etc/nspawn/build/${resource}/ /tmp/

    if test -d /etc/nspawn/build/${resource}/nspawn.postinst.sh; then
        echo "execute nspawn.postinst.sh script in machine with stdin pipe"
        cat - | machinectl shell ${resource} /bin/sh -c \
            "/bin/chmod +x /tmp/nspawn.postinst.sh; /tmp/nspawn.postinst.sh"
    fi

    printf "provision done, power off machine ${resource} "
    machinectl poweroff ${resource}
    while machinectl list -a --no-legend | grep -q ^${resource}; do
        echo -n "."
        sleep 1
    done
    echo " is stopped"
fi
