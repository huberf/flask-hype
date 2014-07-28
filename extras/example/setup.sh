#!/bin/bash
set -e
set -x

# delete
psql -c "DROP DATABASE IF EXISTS hag" "$@"
psql -c "DROP ROLE IF EXISTS hag" "$@"

# role
psql -c "CREATE ROLE hag WITH CREATEDB LOGIN ENCRYPTED PASSWORD 'hag'" "$@"

# db
psql -c "CREATE DATABASE hag WITH OWNER = hag TEMPLATE = template0 ENCODING = 'utf8'" "$@"
psql hag -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public' "$@"
