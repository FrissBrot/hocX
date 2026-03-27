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

2. Build and start:

```bash
docker compose up --build
```

3. Open:

- Frontend through Traefik: <https://hocx.tweber.ch>
- Backend API through Traefik: <https://hocx.tweber.ch/api>
- OpenAPI docs through Traefik: <https://hocx.tweber.ch/docs>

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
- Global `superadmin` remains separate from tenant roles.
- Protocols are treated as snapshots and should never be mutated by template changes.
- Exports are designed to read protocol snapshot data only.

## Local Login And Roles

Seed accounts for a fresh setup:

- `superadmin@hocx.local` / `ChangeMe123!`
- `admin@hocx.local` / `ChangeMe123!`
- `writer@hocx.local` / `ChangeMe123!`
- `reader@hocx.local` / `ChangeMe123!`

Roles:

- `superadmin`: access to all tenants and all permission changes
- `admin`: full access inside the currently selected tenant
- `writer`: may work inside the protocol workspace, but not change structure
- `reader`: may only view workspace data and trigger PDF export

## Public Access With Traefik

The stack includes Traefik for public HTTPS access under `hocx.tweber.ch`.

Requirements:

- the DNS record for `hocx.tweber.ch` must point to this server
- ports `80` and `443` must be reachable from the internet
- Docker must be allowed to bind those ports

Traefik setup files:

- [docker-compose.yml](/docker/hocX/docker-compose.yml)
- [traefik.yml](/docker/hocX/infra/traefik/traefik.yml)

ACME / Let's Encrypt contact:

- `timoweber2006@gmail.com`
