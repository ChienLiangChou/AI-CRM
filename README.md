# SKC Agent OS / AI-CRM

SKC Agent OS is a real-estate CRM and operator console for Kevin Chou's client, listing, and workflow operations. The repository contains a FastAPI backend in `backend/` and a Vite React frontend in `frontend/`.

## Agent Bridge Integration

The product-level Agent Bridge connects SKC Agent OS with two external operator surfaces:

- OpenClaw scoped agents for bounded public research, local-file review, form review, and draft-only workflows.
- Codex Chrome extension handoffs for browser-side inspection in already-authorized tabs.

The integration is deliberately review-gated. SKC Agent OS prepares structured handoff packages, approval requirements, and audit notes. It does not execute OpenClaw commands, change OpenClaw workspaces, store credentials, send messages, submit browser forms, sign documents, or mutate CRM data from a bridge session.

The controlled execution layer adds durable execution tickets. A ticket can be approved by Kevin, handed to OpenClaw or Codex Chrome as a bounded external runner package, and then written back into SKC Agent OS as a reviewed result. Ticket creation, approval, and result recording still do not send, submit, sign, or mutate external accounts.

The source-of-truth memory layer records bridge lifecycle events, execution approvals, external results, and automation activity as reviewable audit history. The Automation Engine v1 prepares scheduled or retried execution tickets only. It never runs OpenClaw, drives Chrome, sends email, submits forms, signs documents, or approves client-facing action.

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
- `GET /api/integrations/agent-bridge/memory`
  - Returns recent source-of-truth memory events for Agent Bridge workflow history.
- `GET /api/integrations/agent-bridge/audit-dashboard`
  - Returns execution, memory, automation, blocked, waiting-approval, and guardrail metrics.
- `GET /api/integrations/agent-bridge/automations`
  - Returns approval-gated automation rules.
- `POST /api/integrations/agent-bridge/automations`
  - Creates a preparation-only automation rule for OpenClaw, Codex Chrome, or SKC internal review.
- `POST /api/integrations/agent-bridge/automations/run-due`
  - Checks due automation rules and prepares waiting-approval execution tickets.
- `POST /api/integrations/agent-bridge/automations/{automation_id}/retry`
  - Prepares a retry ticket within the rule's retry limit.

### Frontend Surface

The frontend exposes the integration at `/agent-bridge`.

The page includes:

- capability cards for SKC Agent OS, OpenClaw, and Codex Chrome extension;
- a bridge composer for workflow context, client, property/task handle, and requested outcome;
- toggles for OpenClaw and Codex Chrome extension handoffs;
- review state, approval requirements, audit notes, and copyable handoff prompts.
- controlled execution tickets with target/profile selection, Kevin approval status, copyable runner packages, and result recording.
- source-of-truth memory and audit dashboard metrics.
- Automation Engine v1 rule creation, due checks, and approval-gated retry preparation.

### Safety Model

- OpenClaw remains a separate workspace family. This app does not modify OpenClaw workspaces, configs, or clean baselines.
- Browser work must use already-authorized tabs and must preserve visible evidence such as listing IDs, attachments, floor plans, dates, and filenames.
- Gmail, WhatsApp, SignNow, Acrobat, MLS/REALM/TRREB, and other external surfaces remain human-review gated.
- Bridge sessions are draft and evidence preparation only. They do not send, sign, submit, purchase, delete, or message externally.
- Execution tickets are bounded runner packages, not unrestricted shell or browser automation.
- Automation rules only create waiting-approval execution tickets. Kevin remains final approver before any external runner scope or client-facing action.

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
