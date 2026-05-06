# Deploy runbook

Operational reference for staging + production. Closes #2122 (supersedes the older #1744).

This document covers **how Sira gets built, where it runs, and what to do when things break**. Read this whole file before your first prod deploy. Emergency-mode skim: jump straight to ["Smoke is RED, what now?"](#smoke-is-red-what-now).

---

## TL;DR

- **Staging** auto-deploys on every `push` to `main`. URL: `https://etutor.elearning.portfolio2.kimbetien.com` (FE) + `https://api.elearning.portfolio2.kimbetien.com` (BE). Server: `deploy@167.86.115.58`.
- **Production** deploys only via manual `workflow_dispatch` with `environment=production`. URL: `https://app.sira-donnia.org` + `https://api.sira-donnia.org`. Server: `deploy@94.250.201.110`.
- **Build pipeline**: GH Actions → `ghcr.io/benidrissa/etutor-digital-ph/{backend,frontend,mms-tts,nllb}` → server pulls changed layers (replaces SCP since 2026-04-05).
- **Hourly prod smoke** runs from `.github/workflows/prod-smoke.yml` (#2118). On failure it auto-opens / comments a tracking issue.
- **Persona E2E suite** runs in PR CI (#2117); `e2e` job in `.github/workflows/ci.yml` against staging.

---

## Topology

### Staging

| Component | Where | Deployed via |
|---|---|---|
| FE | `etutor.elearning.portfolio2.kimbetien.com` | GH Actions → ghcr.io image, pulled by `docker compose` on `167.86.115.58` |
| BE | `api.elearning.portfolio2.kimbetien.com` | Same |
| Postgres / Redis / MinIO / mms-tts / nllb | Same Docker Compose stack on `167.86.115.58:/home/deploy/etutor/` | Static images, rebuilt only on infra changes |

Trigger: any `push` to `main` runs `.github/workflows/deploy.yml` with default `environment=staging`.

### Production

| Component | Where | Deployed via |
|---|---|---|
| FE | `app.sira-donnia.org` | GH Actions → ghcr.io image, pulled by `docker compose` on `94.250.201.110` |
| BE | `api.sira-donnia.org` | Same |
| Shared infra (postgres/redis/minio for *all* tenants + console) | `/home/deploy/etutor/` on `94.250.201.110` — see memory `prod_etutor_shared_infra` for why this is shared | Manual; never stop the shared trio |
| App tier (backend/frontend/celery/mms-tts) | Same host, separate compose | Deployed via `workflow_dispatch` with `environment=production` |

Bare `sira-donnia.org` is a **parked domain** (root → `/lander` → search-network redirect). Never use it as a target. Staging path uses a different domain entirely.

---

## How to deploy

### Staging (automatic)

```bash
git push origin main      # triggers .github/workflows/deploy.yml on main
```

CI runs: lint + test + build → push images to ghcr.io → SSH to staging → `docker compose pull && docker compose up -d`. Watch the run: `gh run watch` (per memory `feedback_deploy_speed.md`: don't block on it; check status once and move on).

### Production (manual)

```bash
gh workflow run deploy.yml -f environment=production
```

Per memory `feedback_never_prod_without_green_staging.md`: only invoke production deploy when:
1. The change has been on staging for at least one validated test cycle,
2. An authenticated smoke against staging has passed (the persona suite at minimum),
3. Someone explicitly typed the word "prod" — `deploy` alone always means staging.

Or use `make prod-deploy` (a thin wrapper, see [Makefile prod-* targets](#makefile-prod--targets)).

### What CI does NOT do (yet)

- **No SHA pinning** — images use `:latest` tag. A subsequent deploy can silently move `:latest`. **#2119 will fix this** by digest-pinning.
- **No pre-deploy DB backup** — if a migration drops a column wrongly, restoring is a manual restore-from-yesterday's pgdump. **#2119 will add a pre-deploy snapshot.**
- **No post-deploy smoke gate** — once images deploy, CI considers the job done. The hourly prod smoke (#2118) catches breakage but with up to 60-minute latency. **#2119 will add a post-deploy synchronous smoke that gates the deploy.**

Until #2119 lands, the operator is the safety net: watch the prod-smoke channel after every deploy.

---

## Rollback

Today (pre-#2119): manual.

```bash
ssh deploy@94.250.201.110
cd /home/deploy/etutor
# Identify the previous good image digest from your local notes / Slack:
# the deploy.yml workflow log lists `docker pull ghcr.io/.../backend@sha256:...`
docker compose pull backend:<previous-tag>     # if you know the tag
docker compose up -d backend
# Or the nuclear option: pull a specific known-good ghcr.io tag for ALL services
# and recreate the whole compose stack.
```

After #2119 lands: `make prod-rollback` will fetch the previously-pinned digest from a recorded artifact and redeploy that.

---

## Backup + restore

Today (pre-#2119): on the prod host, a manual pgdump:

```bash
ssh deploy@94.250.201.110
cd /home/deploy/etutor
docker compose exec -T postgres pg_dump -U postgres santepublique_aof | \
  gzip > backups/pre-manual-$(date +%Y%m%d-%H%M).sql.gz
```

After #2119 lands:
- Pre-deploy snapshot is automatic (workflow step).
- Daily cron snapshot to off-host storage.
- `make prod-backup` for ad-hoc; `make prod-restore-drill` for verification.

Until then, **before any DB-mutating PR ships to prod**, run the manual pgdump above and copy it off-host (e.g. `scp deploy@94.250.201.110:.../*.sql.gz ./local/`).

---

## Smoke is RED, what now?

The hourly cron (`.github/workflows/prod-smoke.yml`) will have already opened or commented on a tracking issue titled `[prod-smoke] Hourly smoke is RED on app.sira-donnia.org`. Each red run downloads the Playwright HTML report + traces as a workflow artifact (30-day retention).

**Triage order** (5-minute time budget; escalate if exceeded):

1. **Open the workflow run** linked from the tracking issue.
2. **Check Sentry** — `https://sentry.io/organizations/sira/projects/sira-prod/` (DSN in `.env.prod.example`). Spike in 5xx? Auth-bypass spike? That's the headline cause.
3. **Check PostHog** — top-of-funnel events still firing? If `/dashboard` traffic dropped to zero, the FE is broken at routing level, not at the smoked endpoint.
4. **Check Traefik logs**:
   ```bash
   ssh deploy@94.250.201.110
   docker logs etutor-traefik --tail 200
   ```
   404 storms = a service container down. Connection refused = a backend container down.
5. **Check service container status**:
   ```bash
   docker compose ps
   docker logs etutor-backend --tail 200
   docker logs etutor-frontend --tail 200
   ```
6. **If a recent deploy is the suspect**: rollback (see above). Don't waste time forensics on a known-failing release; restore service first, dig later.

Categories:
- **Real prod regression** → file a fix issue, link to the tracking issue, **leave the tracking issue open** until the smoke is green for 24h.
- **Transient (network blip, GH Actions runner flake)** → close with a `transient` label.
- **Known fixme** (currently `/sw.js` 404 pending #2113 deploy) — mentioned in the smoke spec; don't open a new tracking issue for these.

---

## Makefile prod-* targets

Thin wrappers around `gh workflow run` + SSH. Run from the repo root.

```bash
make prod-deploy           # gh workflow run deploy.yml -f environment=production
make prod-status           # SSH to prod, docker compose ps + recent logs
make prod-rollback         # (pending #2119) — restore previous-pinned image digest
make prod-backup           # (pending #2119) — manual pgdump + scp off-host
make prod-restore-drill    # (pending #2119) — restore latest backup into a side schema
make prod-smoke            # gh workflow run prod-smoke.yml --ref main (manual smoke)
```

`prod-rollback`, `prod-backup`, `prod-restore-drill` print a `# TODO(#2119)` notice today; #2119 fills them in.

---

## Required GitHub Actions secrets

These must be set on the repo for CI + deploy to work. Verify with `gh secret list`.

| Secret | Used by | Purpose |
|---|---|---|
| `GHCR_TOKEN` | `deploy.yml` | Push images to `ghcr.io` |
| `DEPLOY_KEY_STAGING` | `deploy.yml` | SSH key to `deploy@167.86.115.58` |
| `DEPLOY_KEY_PRODUCTION` | `deploy.yml` | SSH key to `deploy@94.250.201.110` |
| `E2E_LEARNER_PASSWORD` | `ci.yml` (#2117) | Persona suite — staging fixture (set 2026-05-01) |
| `E2E_ORG_OWNER_PASSWORD` | `ci.yml` (#2117) | Same |
| `E2E_SUB_ADMIN_PASSWORD` | `ci.yml` (#2117) | Same |
| `E2E_ADMIN_PASSWORD` | `ci.yml` (#2117) | Same |

Tokens for paid APIs (Anthropic, OpenAI, HeyGen) are managed *on the server's `.env`*, not as GH Actions secrets — CI never touches them.

---

## Common operations

### Tail prod backend logs
```bash
ssh deploy@94.250.201.110 'cd /home/deploy/etutor && docker compose logs -f --tail=100 backend'
```

### Restart a stuck container
```bash
ssh deploy@94.250.201.110 'cd /home/deploy/etutor && docker compose restart celery-worker'
```

### Run an Alembic migration manually on prod
```bash
ssh deploy@94.250.201.110 'cd /home/deploy/etutor && docker compose exec backend uv run alembic upgrade head'
```
Per memory `feedback_never_prod_without_green_staging`: don't do this without staging-validation first.

### One-off Python in the backend container
```bash
ssh deploy@94.250.201.110 \
  'cd /home/deploy/etutor && docker compose exec backend /app/.venv/bin/python -c "..."'
```

---

## Memory references

The following memory entries are load-bearing for prod operations — read them before deviating from the patterns above:

- `production_server.md` — IP, domains, Traefik routing
- `deployment_server.md` — staging server details
- `server_architecture.md` — CI/CD pipeline shape
- `prod_etutor_shared_infra.md` — never stop the shared infra trio
- `feedback_never_prod_without_green_staging.md` — prod-deploy gate
- `feedback_paid_external_apis.md` — don't burn HeyGen/Anthropic/OpenAI on validation re-runs
- `feedback_no_main_branch.md` — never `git checkout main`; let automation handle main
- `feedback_no_manual_merge.md` — never `gh pr merge` from CLI
- `repo_merge_methods.md` — main requires `--squash`, dev uses `--merge`

---

## What's next (out of scope for this PR)

- **#2119** — deploy hardening (SHA pinning, pre-deploy backup, post-deploy smoke gate, auto-rollback). Will fill in the `# TODO(#2119)` placeholders in this doc + Makefile.
- **#2120** — observability audit (Sentry/PostHog instrumentation gaps). Will add explicit alert thresholds to this doc.
- **#2121** — Lighthouse CI gate. Will add `make perf-baseline` and threshold reference.
