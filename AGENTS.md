# SKC Agent OS / AI-CRM Codex Instructions

This repository is the AI-CRM codebase that powers the SKC Agent OS product. Treat the product name `SKC Agent OS` and the repository name `AI-CRM` as referring to the same local system after confirming the Git root and remote.

## First Checks

- Start every repo task by confirming `pwd`, `git rev-parse --show-toplevel`, and `git status --short`.
- Use the current Git root as the source of truth. Past local paths have included both `/Users/kevinchou/SKC Agent OS` and `/Users/kevinchou/ai-crm`, so do not assume a path without checking.
- Before editing, inspect nearby files and follow existing backend and frontend patterns.
- Keep unrelated user changes intact. Stage and commit only the files that belong to the requested task.

## Scope Boundaries

- Do not touch credentials, `.env` files, local token files, OAuth secrets, or deployment secrets unless the user explicitly asks.
- Do not modify OpenClaw workspaces or OpenClaw configuration from this repository unless the user explicitly asks for that exact action.
- Do not apply, pop, or merge stashes unless the user explicitly asks. In particular, do not apply `stash@{0}` without explicit approval.
- Do not add hidden automation, auto-send behavior, Gmail draft creation, Gmail sending, or external messaging without explicit approval.
- Keep Gmail and listing-alert flows approval-gated. Human review is required before emails, messages, offers, contracts, or signature packages are sent.
- Do not broaden a task into backend/frontend behavior changes when the request is documentation, configuration, or repo-instruction only.

## Repo Map

- `backend/` contains the FastAPI backend.
- `frontend/` contains the Vite/React frontend.
- `render.yaml` contains deployment configuration.
- Operational notes that guide agents should live under `docs/ops/` when they are not runtime code.

## 20X Operating Docs

- `docs/ops/SKC_20X_REAL_ESTATE_OPERATING_MODEL.md`
- `docs/ops/SKC_20X_TOOL_INTEGRATION_PLAYBOOK.md`
- `docs/ops/SKC_20X_FIRST_WEEK_USAGE_CHECKLIST.md`
- `docs/ops/SKC_20X_30_DAY_ROADMAP.md`

## Local Commands

- Backend local startup normally runs from `backend/` with `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- Backend tests may require `PYTHONPATH` pointed at the backend path before running `pytest`.
- Frontend local startup normally runs from `frontend/` with `npm run dev -- --host 127.0.0.1`.
- Frontend verification normally uses the package scripts already present in `frontend/package.json`.
- If local port binding is blocked by the environment, report that as an environment limitation instead of treating it as a code regression.

## Engineering Rules

- Prefer the smallest patch that satisfies the request.
- Preserve existing API contracts, UI flows, and data handling unless the user asked for behavior changes.
- When changing backend logic, add or update focused backend tests.
- When changing frontend behavior, run the relevant lint/build/test command when available.
- When working on listing monitoring, approval workflows, Gmail intake, or agent execution, distinguish `blocked`, `waiting_approval`, and successful completion. Do not fake success.
- Keep request-scoped tokens in memory only; do not persist tokens into storage, URLs, task payloads, run results, audit logs, or docs.

## Reporting

- Report exactly what changed, what was verified, and anything that could not be verified.
- For commits, include the final `git status --short` and commit hash.
- Do not push unless the user explicitly asks.
