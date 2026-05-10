# SKC 20X Tool Integration Playbook

## 1. Purpose

This playbook tells Kevin and future agents when to use SKC Agent OS, OpenClaw, Codex App / IDE, and Codex Chrome.

The goal is a controlled 20X operating system: fast preparation, strong auditability, isolated external runners, supervised browser assistance, and Kevin as final approver.

## 2. Decision tree

Start with the task type:

1. Is it a production CRM, listing, match, paperwork, follow-up, approval, or audit workflow?
   - Use SKC Agent OS.
2. Is it code, tests, build, CI, deployment, docs, or repo state?
   - Use Codex App / Codex IDE.
3. Is it low-risk isolated work such as SOP, workflow map, dummy package, dummy email draft, public-only research, or one explicitly approved local file summary?
   - Use OpenClaw in the exact scoped workspace.
4. Is it a supervised browser inspection task in an already-authorized browser session?
   - Use Codex Chrome.
5. Does it send, submit, sign, decide pricing, decide negotiation, decide screening, or touch sensitive data?
   - Stop for Kevin.

For approved external work, use the Agent Bridge execution layer:

1. Create an execution ticket in SKC Agent OS.
2. Confirm the target and execution profile.
3. Mark Kevin approval only after the exact scope is approved.
4. Copy the bounded OpenClaw command or Codex Chrome prompt.
5. Run the external task inside the approved tool/session.
6. Record the result back into SKC Agent OS.
7. Keep client-facing action pending Kevin review.

For recurring preparation work, use the Automation Engine v1 layer:

1. Create an automation rule only for preparation work.
2. Choose OpenClaw, Codex Chrome, or SKC internal review as the target.
3. Choose a scoped execution profile.
4. Use manual, daily, or weekly cadence.
5. Run due checks to create waiting-approval execution tickets.
6. Retry only within the configured retry limit.
7. Record results back into SKC Agent OS memory and audit history.
8. Stop before any send, submit, sign, pricing, negotiation, tenant-screening, or legal/compliance-sensitive decision.

## 3. When to use SKC Agent OS

Use SKC Agent OS for production operating workflows:

- CRM contact review;
- properties;
- Gmail OAuth listing alert intake;
- REALM email extraction;
- listing alert recommendations;
- buyer/renter match;
- listing/CMA support;
- transaction paperwork;
- follow-up;
- conversation closer;
- approvals;
- audit logs;
- run history and review-first workflow state.

SKC Agent OS is the source of truth.

The current product layer includes Agent Bridge memory and an audit dashboard. Use it to inspect:

- execution lifecycle history;
- approval updates;
- result summaries;
- blocked and needs-review states;
- active and due automation rules;
- guardrails that keep external action approval-gated.

## 4. When to use OpenClaw

Use OpenClaw only as an isolated low-risk task runner.

Approved use:

- SOP;
- workflow map;
- internal documentation;
- dummy listing package;
- dummy email draft;
- public-only web research;
- one explicitly approved local file summary.

Do not use OpenClaw for real client/tenant/private data unless Kevin approves exact scope.

Do not merge OpenClaw into the SKC Agent OS repo.

## 5. When to use Codex App / IDE

Use Codex App / IDE for:

- implementation planning;
- backend fixes;
- frontend fixes;
- repo inspection;
- tests;
- builds;
- CI and deployment diagnostics;
- documentation;
- checkpoint commits;
- branch and PR preparation.

Codex App should not send client communications, submit forms, sign documents, or operate logged-in web pages unless the task explicitly calls for an approved tool and scope.

## 6. When to use Codex Chrome

Use Codex Chrome as a supervised browser assistant when Kevin has already opened or authorized the browser context.

Allowed:

- checking Gmail draft existence;
- visually testing SKC Agent OS UI;
- inspecting an already approved signed-in website;
- comparing already-open tabs;
- summarizing a specifically approved Gmail thread.

Not allowed:

- sending;
- submitting;
- signing;
- broad scraping;
- modifying account settings;
- MLS/TRREB/REALM login automation unless Kevin explicitly approves exact scope.

## 7. When task must stop for Kevin

Stop for Kevin before:

- send email;
- submit forms;
- sign documents;
- edit contracts;
- approve or reject real client-facing drafts;
- pricing judgment;
- negotiation strategy;
- legal/compliance-sensitive actions;
- tenant screening actions;
- payment, banking, tax, or ID data handling;
- any high-risk state-changing action.

Agent Bridge execution tickets do not remove these stop conditions. They only make approved external work traceable.

Automation Engine v1 also does not remove these stop conditions. It creates preparation tickets only.

## 8. OpenClaw approved agents

Use explicit scoped agents. Do not use a broad default agent for real workflows.

Approved agent/workspace pattern:

- `standalone`: SOP, workflow map, operating docs, isolated planning.
- `browsertest`: public-only research, no login, no MLS/TRREB/REALM, no private data.
- `formtest`: dummy listing package or form-readiness work only.
- `emaildrafttest`: dummy email draft preparation only, no sending.
- `localfilestest`: one explicitly approved local file summary.

## 9. OpenClaw command templates

These are operating templates. Confirm the installed OpenClaw CLI syntax before execution and run only from the explicitly approved workspace.

### standalone SOP/workflow map

```sh
cd /Users/kevinchou/OpenClaw_Workspaces/openclaw-standalone
openclaw run --agent standalone --task "Create an internal SKC SOP/workflow map for: <approved topic>. Use dummy examples only. Do not access client data. Do not send or submit anything."
```

### browsertest public-only research

```sh
cd /Users/kevinchou/OpenClaw_Workspaces/openclaw-browser-test
openclaw run --agent browsertest --task "Public-only research for: <topic>. No login, no MLS/TRREB/REALM, no client/private data, no downloads, no external messaging. Return URLs, source notes, risks, and a concise checklist."
```

### formtest dummy listing package

```sh
cd /Users/kevinchou/OpenClaw_Workspaces/openclaw-form-test
openclaw run --agent formtest --task "Prepare a dummy listing package checklist for: <dummy scenario>. Use fake data only. Do not submit forms. Do not access real accounts."
```

### emaildrafttest dummy email draft

```sh
cd /Users/kevinchou/OpenClaw_Workspaces/openclaw-email-draft-test
openclaw run --agent emaildrafttest --task "Draft a dummy email for: <dummy scenario>. Use fake names and fake property details. Do not send, queue, or connect to email."
```

### localfilestest one-file summary

```sh
cd /Users/kevinchou/OpenClaw_Workspaces/openclaw-local-files-test
openclaw run --agent localfilestest --task "Summarize only this explicitly approved file: <absolute file path>. Do not read folders. Do not inspect neighboring files. Return summary, key facts, and risks."
```

## 10. Codex Chrome prompt templates

### Testing SKC Agent OS UI

```text
Use Codex Chrome to inspect the already-open SKC Agent OS page at <URL>.
Scope: visual/UI verification only.
Check: <specific page or workflow>.
Do not send, submit, sign, change settings, or access unrelated tabs.
Return visible result, blockers, screenshots or page handles if available, and exact UI issues.
```

### Checking Gmail draft existence

```text
Use Codex Chrome in the already-authorized Gmail tab.
Scope: check whether the draft for <client/workflow> exists.
Do not send, edit, delete, archive, label, or change account settings.
Return draft subject, visible recipient, timestamp if visible, and whether the draft matches the approved workflow.
```

### Summarizing an explicitly approved Gmail thread

```text
Use Codex Chrome in the already-open Gmail thread approved by Kevin.
Scope: summarize only this thread.
Do not open other emails. Do not send, reply, forward, label, archive, or download attachments.
Return timeline, parties, key claims, attachments visible, missing information, and next review question.
```

### Comparing already-open listing tabs

```text
Use Codex Chrome to compare only the already-open listing tabs.
Scope: visible evidence comparison.
Do not login, scrape broadly, open new searches, or submit anything.
Return address, MLS/listing IDs if visible, price, DOM/status if visible, attachments/floor plans if visible, differences, risks, and needs-confirmation notes.
```

## 11. Codex App prompt templates

### Implementation planning

```text
You are in the SKC Agent OS / AI-CRM repo.
Plan only. Do not edit files yet.
Task: <task>.
First inspect pwd, git root, AGENTS.md, docs/ops/SKC_TOOL_ROUTER.md, and git status.
Classify scope and list exact files likely to change.
```

### Backend fix

```text
You are in the SKC Agent OS / AI-CRM repo.
Fix backend issue: <issue>.
Do not touch frontend behavior, env files, credentials, OpenClaw workspaces, or stash@{0}.
Add/update focused backend tests.
Run only relevant backend validation.
```

### Frontend fix

```text
You are in the SKC Agent OS / AI-CRM repo.
Fix frontend issue: <issue>.
Do not touch backend behavior, env files, credentials, OpenClaw workspaces, or stash@{0}.
Follow existing UI patterns.
Run lint/build only if frontend files changed.
```

### Validation-only task

```text
You are in the SKC Agent OS / AI-CRM repo.
Validation only. Do not edit files.
Verify: <workflow/check>.
Report exact command outputs or live blockers.
Do not push.
```

### Checkpoint commit

```text
You are in the SKC Agent OS / AI-CRM repo.
Create a checkpoint commit for the completed scoped work.
Do not include unrelated dirty files.
Do not apply stash@{0}.
Run git status --short, stage only relevant files, commit with: <message>.
Do not push unless explicitly approved.
```

## 12. SKC Agent OS usage templates

### Listing alert review

```text
Run the Listing Alert Recommendation workflow for <client/listing alert>.
Prepare recommendation, match rationale, draft response, and blockers.
Keep status as waiting for approval. Do not send.
```

### Buyer/renter match

```text
Run Buyer Match for <client>.
Compare preferences, budget, areas, property facts, and missing data.
Return ranked matches, risks, and follow-up questions.
```

### Transaction paperwork

```text
Run Transaction Paperwork review for <transaction>.
Prepare checklist, missing fields, deadlines, signatures needed, and risk notes.
Do not edit contracts or send signature packages.
```

### Follow-up

```text
Run Follow-up Agent for <contact/group>.
Prepare follow-up priority, draft language, and reason.
Do not send.
```

## 13. Examples

### Listing alert workflow

Use SKC Agent OS. It owns Gmail OAuth intake, REALM email extraction, client matching, Automatic Mode v1, approval-gated Gmail drafts, and audit trail. Stop before send.

If a low-risk external support task is needed, create an Agent Bridge execution ticket and record the result back into SKC Agent OS.

### Gmail draft check

Use Codex Chrome only in the already-authorized Gmail tab. Check draft existence and visible metadata. Do not send or edit.

### Transaction paperwork

Use SKC Agent OS for the production checklist. Use Codex App only for code/docs changes. Stop before contract edits, signatures, or external submission.

### Public research

Use OpenClaw `browsertest` for public-only research with no login, no private data, and no external messaging. Bring the result back to SKC Agent OS or docs as evidence.

Preferred second-layer path: create an OpenClaw `browsertest_public_research` execution ticket in Agent Bridge, copy the generated package, run it in the approved OpenClaw workspace, then paste the result summary into the ticket.

### UI testing

Use Codex App for automated local tests/build. Use Codex Chrome for supervised visual checks in the already-open app.

Preferred second-layer path: create a Codex Chrome `skc_ui_test` execution ticket, use the generated prompt in the already-open browser session, then record visible results and blockers in SKC Agent OS.

### Code fix

Use Codex App / IDE. Inspect repo state, edit scoped files, run relevant tests, commit only approved changes, and do not push without approval.

## 14. Do-not-use cases

Do not use any tool to:

- send email automatically;
- submit forms;
- sign documents;
- approve real client-facing actions;
- scrape broadly;
- bypass terms;
- automate MLS/TRREB/REALM login without exact approval;
- process sensitive client/tenant data without exact scope;
- apply or merge `stash@{0}` without explicit approval;
- hide automation from Kevin.

## 15. Stop conditions

Stop immediately when:

- task scope becomes unclear;
- credentials, env files, tokens, payments, IDs, tax, or banking data appear;
- a browser action would send, submit, sign, delete, or change account state;
- OpenClaw would need real client/tenant data;
- a website blocks access or terms are unclear;
- production and experimental work would mix;
- unrelated dirty files are present before commit;
- Kevin approval is required.
