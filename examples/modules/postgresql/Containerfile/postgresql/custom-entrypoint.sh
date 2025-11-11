#!/usr/bin/env bash
set -Eeuo pipefail

# configure access to database only with ssl and scram-sha-256 or tls client certs
pg_setup_auth() {
	local pg_hba_current pg_hba
	pg_hba_current=""
	pg_hba="# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
local   replication     all                                     trust
# reject nossl, ssl connect with scram-sha-256 from all or pgpwd nets, or clientcert:verify-full using map:tlsmap from pgmtls net
hostnossl all all 0.0.0.0/0 reject
hostssl all all ${PODMAN_PGMTLS_CIDR} cert clientcert=verify-full map=tlsmap
hostssl all all ${PODMAN_PGPWD_CIDR} scram-sha-256
hostssl all all 0.0.0.0/0 scram-sha-256
"
	if test -e "$PGDATA/pg_hba.conf"; then pg_hba_current="$(cat $PGDATA/pg_hba.conf)"; fi
	if test "$pg_hba" != "$pg_hba_current"; then echo "$pg_hba" > "$PGDATA/pg_hba.conf"; fi
}


# map tls-client-certificate-name to postgresql-username, translate x.y@z.org to x.y_z.org
pg_setup_ident() {
	local pg_ident_current pg_ident
	pg_ident_current=""
	pg_ident="# MAPNAME       SYSTEM-USERNAME         PG-USERNAME
# tlsmap tls-client-certificate-name to-postgresql-username
${POSTGRES_EXTRA_IDENT}
tlsmap /^(.*)@(.*)$ \1_\2
"
	if test -e "$PGDATA/pg_ident.conf"; then pg_ident_current="$(cat $PGDATA/pg_ident.conf)"; fi
	if test "$pg_ident" != "$pg_ident_current"; then echo "$pg_ident" > "$PGDATA/pg_ident.conf"; fi
}

# see also "_main" in "docker-entrypoint.sh"
source /usr/local/bin/docker-entrypoint.sh

# arguments to this script are assumed to be arguments to the "postgres" server (same as "docker-entrypoint.sh"),
# and most "docker-entrypoint.sh" functions assume "postgres" is the first argument (see "_main" over there)
if [ "$#" -eq 0 ] || [ "$1" != 'postgres' ]; then
	set -- postgres "$@"
fi

docker_setup_env
# setup data directories and permissions (when run as root)
docker_create_db_directories

if [ "$(id -u)" = '0' ]; then
	# then restart script as postgres user
	exec gosu postgres "$BASH_SOURCE" "$@"
fi

# only run initialization on an empty data directory
if [ -z "$DATABASE_ALREADY_EXISTS" ]; then
	docker_verify_minimum_env

	# check dir permissions to reduce likelihood of half-initialized database
	ls /docker-entrypoint-initdb.d/ > /dev/null

	docker_init_database_dir

	# our custom auth setup
	pg_setup_auth
	pg_setup_ident

	# PGPASSWORD is required for psql when authentication is required for 'local' connections via pg_hba.conf and is otherwise harmless
	# e.g. when '--auth=md5' or '--auth-local=md5' is used in POSTGRES_INITDB_ARGS
	export PGPASSWORD="${PGPASSWORD:-$POSTGRES_PASSWORD}"
	docker_temp_server_start "$@"

	docker_setup_db
	docker_process_init_files /docker-entrypoint-initdb.d/*

	docker_temp_server_stop
	unset PGPASSWORD
else
	echo >&2 "note: database already initialized in '$PGDATA'!"

	# our custom auth setup
	pg_setup_auth
	pg_setup_ident
fi

exec "$@"
