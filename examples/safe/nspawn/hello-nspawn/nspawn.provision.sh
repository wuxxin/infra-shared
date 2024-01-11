#!/usr/bin/env bash
if test "$1" != "--yes"; then
    echo "Error, missing arg '--yes'"
    exit 1
fi
shift

# save stdin, get os distribution and codename
stdin=$(cat -)
codename=$(lsb_release -c -s)
distribution="$(lsb_release -i -s)"

# delete and create a new set of openssh-server host keys
rm /etc/ssh/ssh_host*
DEBIAN_FRONTEND=noninteractive dpkg-reconfigure --force openssh-server

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

# install nginx and make index.html available on port 80
DEBIAN_FRONTEND=noninteractive apt-get install --yes nginx
cat >/var/www/index.html <<"EOF"
<!DOCTYPE html>
<html>
<head>
<style>pre { font-family: monospace; white-space: pre-wrap; }</style>
</head>
<body>
<pre>
        ><(((((°>
                    ><(((°>
        ><((((°>
    <°)))><            ><(((((°>
                <°))><
            <°)))><         <')))))><
    Hello from a NSpawn Container!
</pre>
</body>
</html>
EOF
