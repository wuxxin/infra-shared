#!/usr/bin/env bash
set -eo pipefail
# set -x
current="$(sudo virsh list --id --state-running | sort | uniq | grep -v "^$" | head -n 1)"
if test -n "$current"; then
    addr="$(sudo virsh guestinfo "$current" | grep "if.1.addr.0.addr" | sed -r "s/[^:]+: (.+)/\1/g")"
    ssh -A -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "core@$addr"
fi
