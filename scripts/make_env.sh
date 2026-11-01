#!/usr/bin/env bash
# Write .env with fresh random secrets. Never overwrites one that exists: its secrets are what
# the databases were created with.
set -euo pipefail

if [[ -e .env ]]; then
    echo ".env already exists: left as it is"
    exit 0
fi

secret() { openssl rand -hex "$1"; }

umask 077 # readable by this user alone
cat >.env <<EOF
# Written by make env. Never commit this file.
PAX_DB_PASSWORD=$(secret 24)

LANGFUSE_USER_EMAIL=raul@pax.local
LANGFUSE_USER_PASSWORD=$(secret 16)

LANGFUSE_PUBLIC_KEY=pk-lf-$(secret 16)
LANGFUSE_SECRET_KEY=sk-lf-$(secret 16)
LANGFUSE_HOST=http://localhost:3000

LANGFUSE_POSTGRES_PASSWORD=$(secret 24)
LANGFUSE_CLICKHOUSE_PASSWORD=$(secret 24)
LANGFUSE_REDIS_PASSWORD=$(secret 24)
LANGFUSE_MINIO_PASSWORD=$(secret 24)
LANGFUSE_SALT=$(secret 24)
LANGFUSE_NEXTAUTH_SECRET=$(secret 24)
LANGFUSE_ENCRYPTION_KEY=$(secret 32)
EOF
echo ".env written"
