# Lightweight ERP backend

FastAPI + PostgreSQL backend for small manufacturers (inventory, BOM, production, purchasing, sales).
Phase 1 (this commit): project skeleton, multi-tenant auth, roles.

## Run with Docker

```bash
cp .env.example .env        # then set JWT_SECRET to a long random string
docker compose up --build
```

API docs: http://localhost:8000/docs

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

## Tests

```bash
pytest -q        # uses in-memory SQLite, no database needed
```

## Endpoints (v1)

| Method | Path | Notes |
| --- | --- | --- |
| POST | /api/v1/auth/register-company | Creates a tenant and its owner, returns tokens |
| POST | /api/v1/auth/login | Returns access + refresh tokens |
| POST | /api/v1/auth/refresh | Exchange a refresh token for new tokens |
| GET | /api/v1/me | Current user |
| GET | /api/v1/tenant | Current company |
| GET, POST | /api/v1/users | Manager or owner only |

## Layout

```
app/core/      config, db session, security, errors, dependencies
app/shared/    base model and mixins
app/modules/   one folder per module (auth now; master_data, inventory, ... next)
migrations/    Alembic versions
tests/
```

## Next: Phase 1 remainder, then Phase 2

Master data (items, units, warehouses, partners) and CSV import, then the stock ledger.
Known gaps to close before launch: refresh-token rotation/revocation, login rate limiting, audit log.
