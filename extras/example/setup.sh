#!/bin/bash
set -e
set -x

# delete
psql -c "DROP TABLE IF EXISTS users"
psql -c "DROP TABLE IF EXISTS passwords"
psql -c "DROP DATABASE IF EXISTS hag" "$@"
psql -c "DROP ROLE IF EXISTS hag" "$@"

# role
psql -c "CREATE ROLE hag WITH CREATEDB SUPERUSER REPLICATION LOGIN ENCRYPTED PASSWORD 'hag'" "$@"

# db
psql -c "CREATE DATABASE hag WITH OWNER = hag TEMPLATE = template0 ENCODING = 'utf8'" "$@"
psql hag -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public' "$@"

# table
psql hag -c "CREATE TABLE users ( id uuid, email_address varchar(40), enabled boolean)"
psql hag -c "CREATE TABLE passwords (user_id uuid, hashed varchar(50), enabled boolean)"
