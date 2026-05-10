# SKC Tool Router

Use this guide before choosing tools for SKC Agent OS / AI-CRM work. The goal is to keep each action inside the right boundary and avoid accidental changes to credentials, customer data, external messaging, or unrelated workspaces.

## Default Routing

| User request | Use | Guardrail |
| --- | --- | --- |
| Repo inspection, local code edits, tests, builds, commits | Local shell, file reads, `apply_patch`, Git | Confirm `pwd`, Git root, and status first. Stage only requested files. |
| Backend API, database models, agent runners, scheduler behavior | `backend/` code and focused backend tests | Preserve existing contracts unless behavior change is explicitly requested. |
| Frontend panels, dashboards, local UI behavior | `frontend/` code and frontend verification scripts | Keep changes inside existing components and services unless redirected. |
| Operational runbooks and persistent agent instructions | `docs/ops/` and root `AGENTS.md` | Documentation only; do not change runtime behavior. |
| Gmail intake or listing-alert review | Existing approval-gated app flows | No draft creation, no sending, no persisted tokens, no hidden automation. |
| OpenClaw experiments or workspaces | Only the explicitly named OpenClaw workspace | Do not touch OpenClaw from this repo unless the user asks for that exact scope. |
| Browser, MLS, REALM, AMPRE, TRREB, SignNow, Acrobat, WhatsApp, or email work | Browser/desktop tools only when the user explicitly asks and the session is already authorized | Keep a human-review boundary before external sends, signatures, or offers. |

## Decision Rules

1. Confirm the current workspace before doing anything that can modify files.
2. If the request is repo-only, stay inside the Git worktree.
3. If the request is documentation or instructions, do not modify backend or frontend behavior.
4. If the request touches credentials, secrets, `.env` files, OAuth tokens, or deployment tokens, stop unless the user explicitly asked for credential work.
5. If a task asks for Gmail, messaging, offers, contracts, or signature packages, prepare drafts or analysis only and wait for explicit human approval before sending or submitting.
6. If the user asks whether something is working, verify both the relevant local or CI evidence and the real runtime/deployed surface when available. If verification is blocked, report the blocker directly.
7. If the user asks to commit, stage only the files that belong to the task and leave unrelated dirty files alone.
8. If stashes exist, inspect only when useful. Do not apply, pop, merge, or delete a stash unless the user explicitly asks.

## SKC Workflow Boundaries

- Listing alert and daily market scan automation may prepare recommendations, packets, and status outputs, but they must not auto-contact clients or external parties.
- Approval states matter. Treat `blocked`, `waiting_approval`, `duplicate_skipped`, and success as separate outcomes.
- Gmail access must remain read-only unless the user explicitly asks for a different mode and approves the risk.
- OpenClaw is a separate workspace family. Do not route local repo tasks into OpenClaw, and do not route OpenClaw tasks back into this repo unless the user asks for a bridge.
- Real-estate browser tasks must be grounded in visible evidence: listing facts, attachments, floor plans, comparable IDs, conditions, deadlines, and file names.

## Stop Conditions

Stop and ask for approval when a next step would:

- send or submit anything externally;
- alter credentials, token storage, or env files;
- apply or merge a stash;
- touch OpenClaw workspaces outside an explicitly approved scope;
- widen a documentation-only task into runtime behavior changes;
- stage unrelated files.
