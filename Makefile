.PHONY: dev-infra dev-infra-down backend-install backend-dev backend-lint backend-test \
       backend-celery-worker backend-celery-beat backend-celery-flower \
       frontend-install frontend-dev frontend-lint frontend-test \
       db-migrate db-revision lint test \
       prod-deploy prod-status prod-rollback prod-backup prod-restore-drill prod-smoke

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

backend-celery-worker:
	cd backend && uv run celery -A app.tasks.celery_app worker --loglevel=info

backend-celery-beat:
	cd backend && uv run celery -A app.tasks.celery_app beat --loglevel=info

backend-celery-flower:
	cd backend && uv run celery -A app.tasks.celery_app flower

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

# Production operations — see DEPLOY.md for full context.
PROD_HOST=deploy@94.250.201.110
PROD_DIR=/home/deploy/etutor

prod-deploy:
	gh workflow run deploy.yml -f environment=production
	@echo "Dispatched. Watch with: gh run watch  (or check the Actions tab)"

prod-status:
	ssh $(PROD_HOST) 'cd $(PROD_DIR) && docker compose ps && echo "---" && docker compose logs --tail=20'

prod-smoke:
	gh workflow run prod-smoke.yml --ref main
	@echo "Manual smoke dispatched. Tail with: gh run watch"

prod-rollback:
	@echo "TODO(#2119): record previous-pinned digest in deploy.yml, fetch + redeploy here."
	@echo "  Today: ssh $(PROD_HOST), docker compose pull <previous-tag>, docker compose up -d."
	@echo "  See DEPLOY.md > Rollback section."
	@false

prod-backup:
	@echo "TODO(#2119): automated pgdump + scp off-host. For now do it manually:"
	@echo "  ssh $(PROD_HOST)"
	@echo "  cd $(PROD_DIR)"
	@echo "  docker compose exec -T postgres pg_dump -U postgres santepublique_aof | gzip > backups/manual-\$$(date +%Y%m%d-%H%M).sql.gz"
	@echo "  scp deploy@host:.../*.sql.gz off-host-storage/"
	@false

prod-restore-drill:
	@echo "TODO(#2119): restore the latest backup into a side schema and validate."
	@echo "  See DEPLOY.md > Backup + restore."
	@false
