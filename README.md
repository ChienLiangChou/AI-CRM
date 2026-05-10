# SKC Agent OS / AI-CRM

SKC Agent OS is a real-estate CRM and operator console for Kevin Chou's client, listing, and workflow operations. The repository contains a FastAPI backend in `backend/` and a Vite React frontend in `frontend/`.

## Agent Bridge Integration

The product-level Agent Bridge connects SKC Agent OS with two external operator surfaces:

- OpenClaw scoped agents for bounded public research, local-file review, form review, and draft-only workflows.
- Codex Chrome extension handoffs for browser-side inspection in already-authorized tabs.

The integration is deliberately review-gated. SKC Agent OS prepares structured handoff packages, approval requirements, and audit notes. It does not execute OpenClaw commands, change OpenClaw workspaces, store credentials, send messages, submit browser forms, sign documents, or mutate CRM data from a bridge session.

The controlled execution layer adds durable execution tickets. A ticket can be approved by Kevin, handed to OpenClaw or Codex Chrome as a bounded external runner package, and then written back into SKC Agent OS as a reviewed result. Ticket creation, approval, and result recording still do not send, submit, sign, or mutate external accounts.

### Backend API

- `GET /api/integrations/agent-bridge/status`
  - Returns the SKC Agent OS, OpenClaw, and Codex Chrome extension capability surfaces.
  - Marks the bridge as `ready_for_handoff`.
  - Confirms `direct_external_actions` is `false`.
- `POST /api/integrations/agent-bridge/sessions`
  - Accepts SKC workflow context, optional client/property handles, and target toggles.
  - Returns OpenClaw and/or Codex Chrome extension handoff prompts.
  - Returns approval requirements and audit notes for operator review.
- `GET /api/integrations/agent-bridge/executions`
  - Returns recent controlled execution tickets.
- `POST /api/integrations/agent-bridge/executions`
  - Creates an approval-gated external runner ticket for OpenClaw, Codex Chrome, or SKC internal review.
- `POST /api/integrations/agent-bridge/executions/{run_id}/approve`
  - Marks Kevin approval for the bounded ticket scope.
- `POST /api/integrations/agent-bridge/executions/{run_id}/result`
  - Records the external runner or browser result back into SKC Agent OS for human review.

### Frontend Surface

The frontend exposes the integration at `/agent-bridge`.

The page includes:

- capability cards for SKC Agent OS, OpenClaw, and Codex Chrome extension;
- a bridge composer for workflow context, client, property/task handle, and requested outcome;
- toggles for OpenClaw and Codex Chrome extension handoffs;
- review state, approval requirements, audit notes, and copyable handoff prompts.
- controlled execution tickets with target/profile selection, Kevin approval status, copyable runner packages, and result recording.

### Safety Model

- OpenClaw remains a separate workspace family. This app does not modify OpenClaw workspaces, configs, or clean baselines.
- Browser work must use already-authorized tabs and must preserve visible evidence such as listing IDs, attachments, floor plans, dates, and filenames.
- Gmail, WhatsApp, SignNow, Acrobat, MLS/REALM/TRREB, and other external surfaces remain human-review gated.
- Bridge sessions are draft and evidence preparation only. They do not send, sign, submit, purchase, delete, or message externally.
- Execution tickets are bounded runner packages, not unrestricted shell or browser automation.

## Local Development

Backend:

```sh
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```sh
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

## Verification

Backend tests:

```sh
cd backend
PYTHONPATH=. pytest
```

Frontend checks:

```sh
cd frontend
npm run lint
npm run build
```
