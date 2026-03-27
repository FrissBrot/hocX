# hocX

Monorepo for a protocol and template management application with:

- Frontend: Next.js App Router + TypeScript
- Backend: FastAPI + SQLAlchemy 2.x
- Migrations: Alembic
- Database: PostgreSQL
- Files: local filesystem for uploads, LaTeX templates, generated exports

## Current Scope

This repository contains a Docker-first starter implementation with:

- Docker Compose for `frontend`, `backend`, and `db`
- initial FastAPI app with modular route structure
- initial Next.js App Router UI shell
- SQLAlchemy base models and services scaffold
- Alembic initial migration based on the provided PostgreSQL schema
- placeholder LaTeX template structure

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

- Frontend: <http://localhost:3000>
- Backend API: <http://localhost:8000>
- OpenAPI docs: <http://localhost:8000/docs>

## Database

The backend expects PostgreSQL. The initial Alembic migration contains:

- core tenant/user/role tables
- template and protocol tables
- content tables for text/todos/images/display snapshots
- export cache and stored file metadata
- `create_protocol_from_template(...)`

Run migrations inside the backend container:

```bash
docker compose exec backend alembic upgrade head
```

## Notes

- OIDC is intentionally not implemented yet.
- The schema already contains OIDC preparation fields on `app_user`.
- Protocols are treated as snapshots and should never be mutated by template changes.
- Exports are designed to read protocol snapshot data only.

