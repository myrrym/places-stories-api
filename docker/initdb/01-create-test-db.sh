#!/bin/bash
# Runs once, on first initialisation of the Postgres volume.
# Tests get their own database so a test run never collides with the
# migrated development database sitting in the same server.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE DATABASE places_test OWNER $POSTGRES_USER;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname places_test \
    -c "CREATE EXTENSION IF NOT EXISTS postgis;"
