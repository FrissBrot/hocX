# hocX

Monorepo for a protocol and template management application with:

- Frontend: Next.js App Router + TypeScript
- Backend: FastAPI + SQLAlchemy 2.x
- Migrations: Alembic
- Database: PostgreSQL
- Files: local filesystem for uploads, LaTeX templates, generated exports

## Current Scope

This repository contains a Docker-first starter implementation with:

- Docker Compose for `traefik`, `frontend`, `backend`, and `db`
- initial FastAPI app with modular route structure
- initial Next.js App Router UI shell
- SQLAlchemy models aligned to the V1 PostgreSQL schema
- Alembic initial migration based on the provided PostgreSQL schema
- placeholder LaTeX template structure
- seeded lookup/master bootstrap data for local development

## Project Structure

```text
frontend/
  app/
  components/
  lib/
  types/
backend/
  app/
    api/routes/
    core/
    db/
    models/
    repositories/
    schemas/
    services/
  alembic/
storage/
  uploads/
  exports/
  latex_templates/
```

## Quick Start

1. Copy environment defaults if needed:

```bash
cp .env.example .env
```

2. Start local development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Shortcut via script:

```bash
./scripts/dev.sh
./scripts/dev.sh stop
./scripts/dev.sh down
./scripts/dev.sh up --profile docs --profile scan
```

3. Open:

- Main app: <http://localhost:3000>
- Backend API / OpenAPI: <http://localhost:8000>
- Abgabebox frontend: <http://localhost:3001>
- Abgabebox backend: <http://localhost:8001>

Optional dev profiles:

- `--profile scan`: starts `clamav` for real upload scanning
- `--profile docs`: starts the docs site on <http://localhost:3002>
- `--profile edge`: starts the local Traefik edge stack

If you explicitly want the source-built server-style stack that mirrors the current
`hocx.example.com` setup more closely, use:

```bash
docker compose up --build
```

## Database

The backend expects PostgreSQL. The initial Alembic migration now builds the composite section/block model:

- core tenant/user/role tables
- `template_element` as section/container rows
- `template_element_block` as nested predefined blocks inside a section
- `protocol_element` as snapshot section/container rows
- `protocol_element_block` as nested protocol block snapshots
- content tables for text/todos/images/display snapshots linked to protocol blocks
- export cache and stored file metadata
- `create_protocol_from_template(...)`

The raw first-setup SQL is stored at:

- [first_setup.sql](/docker/hocX/backend/sql/first_setup.sql)

Migrations run automatically when the backend container starts. You can still run them manually:

```bash
docker compose exec backend alembic upgrade head
```

## Step 2 Status

The database foundation currently includes:

- initial schema as an Alembic migration
- static seed data for `role`, `event_category`, `element_type`, `render_type`, and `todo_status`
- a default tenant and starter document/template records for local development
- SQLAlchemy models for all V1 tables in the provided schema

Useful verification commands:

```bash
docker compose exec backend alembic current
docker compose exec db psql -U hocx -d hocx -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';"
docker compose exec db psql -U hocx -d hocx -c "SELECT * FROM role;"
```

## Notes

- OIDC is intentionally not implemented yet.
- The schema already contains OIDC preparation fields on `app_user`.
- Local login is active for V1 and isolated behind `/api/auth/*`.
- Users are systemwide, while `user_tenant_role` stores tenant-specific permissions.
- Cross-tenant access lives exclusively in the separate platform-admin panel (see below) -
  no customer/tenant user can ever see or manage more than the tenants they are a member of.
- Protocols are treated as snapshots and should never be mutated by template changes.
- Exports are designed to read protocol snapshot data only.

## Local Login And Roles

Seed accounts for a fresh setup:

- `admin@hocx.local` / `ChangeMe123!`
- `writer@hocx.local` / `ChangeMe123!`
- `reader@hocx.local` / `ChangeMe123!`

Roles (all tenant-scoped via `user_tenant_role`):

- `admin`: full access inside the currently selected tenant
- `writer`: may work inside the protocol workspace, but not change structure
- `reader`: may only view workspace data and trigger PDF export
- `kassier`: reader access plus full finance and fines management

## Platform-Admin Panel

`/admin` is a separate operator area with its own login, its own `platform_admin` accounts
table, and its own session cookie (`hocx_admin_session`) - entirely independent from the
customer `app_user`/session system. It is the only place with an overview across all tenants
and all users, and the only place tenants get created or two `app_user` accounts get merged.

The first platform-admin account is bootstrapped from `INITIAL_ADMIN_EMAIL` /
`INITIAL_ADMIN_PASSWORD` env vars on first startup (only when the `platform_admin` table is
still empty); further admins are managed through the panel itself under `/admin/admins`.

In the Traefik deployment, both `/admin` and `/api/admin` are removed from the public main
domain. They are served on `https://${TRAEFIK_ADMIN_DOMAIN}` through the `adminsecure`
entrypoint, whose host port defaults to `127.0.0.1:8443`. It is intended as the host-side
target for an OpenZiti service; do not add a public `0.0.0.0` binding. The public TLS
certificate is issued using Cloudflare DNS-01 with the restricted `CF_DNS_API_TOKEN`.
The token needs `Zone:Zone:Read` and `Zone:DNS:Edit` for the `hocx.ch` zone only; Traefik
receives this token explicitly and does not inherit the application's other `.env` secrets.

The corresponding OpenZiti service must intercept `${TRAEFIK_ADMIN_DOMAIN}:443` on clients and use
`127.0.0.1:8443` as its host-side TCP target. TLS is passed through to Traefik (do not
terminate or replace TLS in the tunnel), so the browser's SNI and `Host` remain
`${TRAEFIK_ADMIN_DOMAIN}` and match the public certificate.

## Public Access With Traefik

The stack includes Traefik for public HTTPS access under `your-domain.example.com`.

Requirements:

- the DNS record for `your-domain.example.com` must point to this server
- ports `80` and `443` must be reachable from the internet
- Docker must be allowed to bind those ports

Traefik setup files:

- [docker-compose.yml](/docker/hocX/docker-compose.yml)
- [traefik.yml](/docker/hocX/infra/traefik/traefik.yml)

ACME / Let's Encrypt contact:

- Set via `ACME_EMAIL` in `.env`
