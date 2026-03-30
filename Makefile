.PHONY: dev-infra dev-infra-down backend-install backend-dev backend-lint backend-test \
       frontend-install frontend-dev frontend-lint frontend-test \
       db-migrate db-revision lint test

# Infrastructure
dev-infra:
	docker compose up -d

dev-infra-down:
	docker compose down

# Backend
backend-install:
	cd backend && uv sync

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

backend-test:
	cd backend && uv run pytest

# Frontend
frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-lint:
	cd frontend && npm run lint

frontend-test:
	cd frontend && npm test

# Database
db-migrate:
	cd backend && uv run alembic upgrade head

db-revision:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

# Combined
lint: backend-lint frontend-lint

test: backend-test frontend-test
