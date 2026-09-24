#!/usr/bin/env sh
# Generates a self-contained `.env.dev` for CI and fresh local checkouts.
# None of the values here are secrets:
#   - PostgreSQL credentials match the docker-compose `db` service defaults
#     (fobos/fobos) — dev-only, same as in `docker-compose.yml`.
#   - DJANGO_SECRET_KEY is generated randomly at each run, never committed.
# Production still runs on the gitignored `.env.prod`.

set -eu

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    awk 'BEGIN{srand(); s=""; for(i=0;i<64;i++) s=s sprintf("%x", int(rand()*16)); print s}'
  fi
}

cat > .env.dev <<EOF
DJANGO_SECRET_KEY=$(generate_secret)
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
POSTGRES_DB=fobos
POSTGRES_USER=fobos
POSTGRES_PASSWORD=fobos
POSTGRES_HOST=db
POSTGRES_PORT=5432
APP_BASE_URL=http://localhost:8000
JWT_ACCESS_HOURS=4
JWT_REFRESH_DAYS=7
FOBOS_USE_DEMO_ADAPTERS=true
EMAIL_VERIFICATION_MAX_AGE_SECONDS=86400
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_PORT=587
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=fobos@example.com
EOF