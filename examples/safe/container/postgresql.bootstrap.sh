#!/usr/bin/env bash
echo "$0: Overwriting pg_hba.conf, pg_ident.conf"
cat > /var/lib/postgresql/data/pg_hba.conf <<"EOF"
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
local   replication     all                                     trust
host    replication     all             127.0.0.1/32            trust
host    replication     all             ::1/128                 trust
# reject nossl, ssl connect with scram-sha-256 or clientcert:verify-full using map:tlsmap
hostnossl all all 0.0.0.0/0 reject
hostssl all all 0.0.0.0/0 scram-sha-256
hostssl all all 0.0.0.0/0 cert clientcert=verify-full map=tlsmap
EOF
cat > /var/lib/postgresql/data/pg_ident.conf <<"EOF"
# MAPNAME       SYSTEM-USERNAME         PG-USERNAME
# add mapping tlsmap for tls client certificate to postgresql username
tlsmap          /^(.*)@{{ HOSTNAME|replace(".", "\.") }}$    \1
EOF
