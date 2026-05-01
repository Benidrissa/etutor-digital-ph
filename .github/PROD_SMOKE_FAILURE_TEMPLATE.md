---
title: "[prod-smoke] Hourly smoke is RED on app.sira-donnia.org"
labels: ["bug", "priority:high", "observability", "automated"]
assignees: []
---

The hourly production read-only smoke ([`./.github/workflows/prod-smoke.yml`](../../.github/workflows/prod-smoke.yml)) failed at least once. While this issue is open, subsequent failures append a comment instead of spamming new issues.

**Latest failing run**: {{ env.RUN_URL }}

**What the smoke checks**: see [`frontend/e2e/smoke/critical-paths.spec.ts`](../../frontend/e2e/smoke/critical-paths.spec.ts) — anonymous-only, read-only assertions on `app.sira-donnia.org`:
- backend `/health`
- public settings endpoint
- PWA service worker `/sw.js` (currently `.fixme` until #2113 deploys)
- anonymous course catalog / curricula index / about / login form
- English locale parity
- protected admin/user endpoints reject anonymous (auth-bypass sentinels)

**What to do**:

1. Open the workflow run linked above.
2. Download the `prod-smoke-{run_id}` artifact (Playwright HTML report + traces).
3. The report identifies which assertion failed. Trace files (under `test-results/`) replay the full browser session.
4. Triage:
   - If a real prod regression: file a fix issue, link it here, and **leave this open** until the smoke goes green again.
   - If a transient (network, GH Actions infra): close this with a `transient` label.
5. When the next green run occurs, the smoke job does **not** auto-close this issue (intentional — keeps a paper trail). Close manually after triage.
