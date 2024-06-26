#!/usr/bin/env bash
set -eo pipefail

if test "$1" != "--provision"; then
    cat << EOF
Usage: $0 --provision

Provision bootstrap script. Expects an dpkg based linux.
DONT execute on an already configured system.
THIS WILL OVERWRITE ALREADY EXISTING FILES.
EOF
    exit 1
fi
shift

# save stdin for later usage
stdin=$(cat -)

codename=$(lsb_release -c -s)
distribution="$(lsb_release -i -s)"
echo "Provision running on distribution: $distribution , codename: $codename"

# create user, copy skeleton files
USERNAME="user"
HOME="/home/$USERNAME"
adduser --disabled-password --gecos ",,," --home "$HOME" "$USERNAME" || true
cp -r /etc/skel/. "$HOME/."
install -o "$USERNAME" -g "$USERNAME" -m "0700" -d "$HOME/.ssh"

# write authorized_keys if supplied
authorized_keys=""
head='# ---BEGIN OPENSSH AUTHORIZED KEYS---'
bottom='# ---END OPENSSH AUTHORIZED KEYS---'
if echo "$stdin" | grep -qPz "(?s)$head.*$bottom"; then
    authorized_keys=$(echo "$stdin" | awk "/$head/,/$bottom/")
fi
echo "$authorized_keys" >"$HOME/.ssh/authorized_keys"
chown "$USERNAME:$USERNAME" "$HOME/.ssh/authorized_keys"
chmod "0600" "$HOME/.ssh/authorized_keys"

# install openssh server and nginx, make index.html available on port 80
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install --yes openssh-server nginx
mkdir -p /var/www/html
cat >/var/www/html/index.html <<"EOF"
<!DOCTYPE html>
<html>
<head>
<style>pre { font-family: monospace; font-size: 2em; white-space: pre; }</style>
</head>
<body>
<pre>
           ><(((((>

                    ><(((>
        ><((((>

    <)))><            ><(((((>
                <))><

         <)))><    <)))))><

    Hello from a NSpawn Container!
</pre>
</body>
</html>
EOF
systemctl start ssh
systemctl start nginx
