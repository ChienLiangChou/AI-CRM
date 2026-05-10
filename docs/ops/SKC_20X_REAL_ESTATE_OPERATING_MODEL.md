# SKC 20X Real Estate Operating Model

## 1. Purpose

This document defines the operating model for turning SKC Agent OS into a 20X AI-assisted one-person real estate company.

The goal is to make Kevin faster, more consistent, and better prepared without removing Kevin's final control over client relationships, legal/compliance-sensitive work, pricing judgment, negotiation, sending, signing, or tenant-screening decisions.

## 2. What "20X one-person real estate company" means

A 20X one-person real estate company means AI handles most routine preparation work while Kevin keeps final authority.

AI should handle 80-90% of:

- intake sorting;
- client and property context preparation;
- listing alert analysis;
- buyer/renter match preparation;
- comparable and CMA prep;
- paperwork checklist preparation;
- Gmail draft preparation;
- follow-up drafting;
- source comparison;
- browser evidence capture;
- SOP and workflow documentation;
- audit visibility and run summaries.

Kevin should spend most of his time on:

- client-facing judgment;
- final communication;
- offer strategy;
- negotiation;
- pricing;
- compliance-sensitive review;
- relationship decisions;
- exceptions and overrides.

## 3. What it does NOT mean

This model is not uncontrolled autonomous brokerage.

It does not mean:

- auto-sending emails;
- auto-submitting forms;
- auto-signing documents;
- auto-approving client-facing actions;
- broad scraping;
- bypassing website terms;
- hidden automation;
- MLS/TRREB/REALM login automation without exact approval;
- processing sensitive client or tenant data without exact file/email/thread/task scope;
- merging experimental stash work into production checkpoints.

The target is supervised leverage, not unbounded autonomy.

## 4. SKC Agent OS as source of truth

SKC Agent OS is the production system and the source of truth.

It owns:

- CRM contacts;
- properties;
- Gmail OAuth;
- listing alerts;
- buyer/renter match;
- listing/CMA support;
- transaction paperwork;
- follow-up;
- conversation closer;
- approvals;
- audit logs;
- workflow runs;
- review-first operating state.

External tools can prepare, inspect, summarize, or draft. They do not replace SKC Agent OS as the operational record.

## 5. The three-tool operating stack

The stack has four practical surfaces:

- **SKC Agent OS**: production real estate operating system and source of truth.
- **OpenClaw**: external low-risk isolated task runner for SOPs, workflow maps, dummy package work, dummy email drafts, public-only research, and explicitly approved one-file summaries.
- **Codex App / Codex IDE**: code, repo, implementation, tests, build, CI, deployment, documentation, and checkpoint worker.
- **Codex Chrome**: supervised browser assistant for signed-in browser tasks that Kevin has explicitly scoped.

Kevin remains the final approver across the stack.

## 6. Core business workflows

Core production workflows belong in SKC Agent OS:

- Follow-up Agent v1;
- Client Conversation Closer Agent v1;
- Listing / CMA Agent v1;
- Buyer Match Agent v1;
- Listing Alert Recommendation Workflow v1;
- Transaction Paperwork v1;
- Operations / Compliance Visibility Module v1.

Listing Alert Recommendation includes:

- Gmail OAuth production intake;
- REALM email extraction;
- client match hardening;
- Automatic Mode v1;
- approval-gated Gmail draft flow;
- no auto-send.

## 7. Approval-gated communication model

Every client-facing or external-facing action must pass through a review gate.

AI may prepare:

- suggested replies;
- Gmail drafts;
- offer-response talking points;
- listing recommendation summaries;
- paperwork checklists;
- client follow-up scripts;
- comparable summaries.

Kevin must approve:

- sending;
- signing;
- submitting;
- offer strategy;
- negotiation position;
- pricing;
- legal/compliance-sensitive language;
- rental screening outcomes;
- final client relationship decisions.

## 8. Human review boundaries

Stop for Kevin before:

- sending emails, texts, WhatsApp messages, or client notes;
- submitting forms or portals;
- signing or editing signature packages;
- editing contracts or offers;
- approving/rejecting client-facing drafts;
- deciding pricing or negotiation strategy;
- acting on legal/compliance-sensitive material;
- handling payment, banking, tax, ID, or tenant-screening data;
- using a logged-in site outside exact approved scope.

## 9. Safe automation boundaries

Safe automation is allowed when it remains preparation-only and audit-visible.

Allowed:

- classify and summarize incoming workflow context;
- prepare draft recommendations;
- prepare Gmail drafts without sending;
- prepare comparison tables;
- create checklists;
- prepare follow-up tasks;
- generate audit notes;
- create approval-gated external runner tickets;
- record external runner results into source-of-truth memory;
- run preparation-only automation due checks;
- create low-risk OpenClaw dummy artifacts;
- visually check approved browser state using Codex Chrome.

Not allowed:

- hidden automation;
- broad scraping;
- auto-send;
- auto-submit;
- auto-sign;
- credential or env-file changes without approval;
- OpenClaw access to real client/tenant data without exact scope.

## 10. Current completed v1 capabilities

Approved v1 Manual Mode modules:

- Follow-up Agent v1;
- Client Conversation Closer Agent v1;
- Listing / CMA Agent v1;
- Buyer Match Agent v1;
- Listing Alert Recommendation Workflow v1;
- Transaction Paperwork v1;
- Operations / Compliance Visibility Module v1.

Listing Alert Recommendation v1 has an approval-gated production path with Gmail OAuth intake, REALM extraction, client match hardening, Automatic Mode v1, and Gmail draft preparation without auto-send.

Agent Bridge product-layer integration now includes:

- Layer 1: SKC Agent OS handoff packages for OpenClaw and Codex Chrome;
- Layer 2: controlled execution tickets with Kevin approval gates and result recording;
- Layer 3: source-of-truth memory events and audit dashboard metrics;
- Layer 4: Automation Engine v1 for preparation-only rules, due checks, and retry tickets.

These layers do not execute OpenClaw directly, drive Chrome directly, send, submit, sign, scrape broadly, or approve client-facing decisions.

## 11. Current next-phase / experimental surfaces

Do not treat these as completed production modules unless Kevin explicitly approves:

- Strategy Coordination;
- Event Strategy Review;
- Daily Market Scan;
- Authenticated MLS Access;
- direct OpenClaw shell execution from SKC Agent OS;
- experimental work in `stash@{0}`.

These may be planned, tested, or documented, but they should not be mixed into release checkpoints without explicit approval.

## 12. 80-90% AI preparation / 10-20% Kevin judgment model

The operating model is:

- AI prepares the file.
- AI compares source evidence.
- AI drafts the options.
- AI surfaces blockers and missing data.
- AI proposes the next step.
- Kevin decides.

This keeps Kevin's time focused on judgment, relationships, strategy, exceptions, compliance, and negotiation.

## 13. Daily operating rhythm

Daily 5-10 minute rhythm:

1. Open SKC Agent OS.
2. Review new listing alerts, follow-up prompts, buyer/renter matches, and paperwork visibility.
3. Let AI prepare drafts, comparisons, and checklists.
4. Approve, reject, or revise only the highest-value next actions.
5. Record blocked reasons, overrides, draft quality, and time saved.
6. Use Codex Chrome only for explicitly approved browser evidence checks.
7. Use OpenClaw only for low-risk isolated tasks.

## 14. Risks and guardrails

Main risks:

- over-automation;
- hidden sends or submissions;
- accidental use of sensitive data;
- mixing experimental code with production;
- treating draft output as final judgment;
- website terms or login-boundary violations;
- stale or unsupported listing facts.

Guardrails:

- SKC Agent OS remains the source of truth.
- Kevin remains final approver.
- External tools are bounded and scoped.
- Every high-risk action stops for human approval.
- Drafts and browser checks must preserve source evidence.
- Experimental work stays out of production checkpoints.

## 15. Completion definition for future phases

A future phase is complete only when:

- the workflow has a clear source of truth in SKC Agent OS;
- approval gates are visible;
- audit logs or run summaries exist;
- tests or validation evidence exist where appropriate;
- failure modes are explicit;
- Kevin can override or stop the workflow;
- no auto-send, auto-submit, or auto-sign behavior is introduced;
- docs explain when to use SKC Agent OS, OpenClaw, Codex App, and Codex Chrome.
