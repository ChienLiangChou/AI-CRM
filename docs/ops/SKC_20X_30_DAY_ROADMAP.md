# SKC 20X 30-Day Roadmap

## 1. Purpose

This roadmap turns SKC Agent OS into a practical 20X AI-assisted one-person real estate company without uncontrolled autonomy.

The sequence is:

1. Use v1 in real work.
2. Collect friction.
3. Fix the highest-friction workflow.
4. Build source-of-truth memory.
5. Add Automation Engine v1 only after real usage proves what should be automated.

## 2. Week 1: use v1 and collect friction

Goal: use the approved v1 workflows daily.

Run:

- Listing Alert Recommendation Workflow v1;
- Follow-up Agent v1;
- Client Conversation Closer Agent v1;
- Listing / CMA Agent v1;
- Buyer Match Agent v1;
- Transaction Paperwork v1;
- Operations / Compliance Visibility Module v1.

Record:

- blocked reason;
- override used;
- draft quality;
- time saved;
- missing data;
- next fix candidate.

Do not build large new modules in week 1 unless a production blocker prevents real use.

## 3. Week 2: fix highest-friction workflow

Goal: improve the workflow that produced the most useful but blocked output in week 1.

Possible fixes:

- clearer blocked reasons;
- better client match logic;
- better duplicate skipped references;
- better draft quality;
- better source evidence display;
- better approval queue;
- better audit trail;
- better operator notes.

Pick one workflow. Do not widen scope across the whole system.

## 4. Week 3: build source-of-truth memory layer

Goal: make SKC Agent OS better at remembering reusable operating context.

Candidate memory objects:

- client preference memory;
- property/listing memory;
- recurring blocked reasons;
- draft-quality feedback;
- Kevin override patterns;
- deal-specific risk notes;
- workflow-specific SOPs;
- approval outcomes.

Memory must be visible, reviewable, and correctable. It should not silently change client-facing behavior.

## 5. Week 4: Automation Engine v1

Goal: automate preparation only after real friction data identifies the safest and most valuable target.

Controlled execution layer v1 is the first safe bridge toward Automation Engine v1. It should:

- schedule preparation tasks;
- create run records;
- surface blocked states;
- prepare drafts or recommendations;
- route to approval;
- preserve audit notes;
- let Kevin stop or override.
- create external runner tickets for OpenClaw and Codex Chrome;
- require Kevin approval before external execution scope is treated as ready;
- record external runner results back into SKC Agent OS.

Controlled execution layer v1 and future Automation Engine v1 must not:

- auto-send;
- auto-submit;
- auto-sign;
- scrape broadly;
- act on sensitive data without exact approval;
- bypass terms;
- hide automation.

## 6. What not to build yet

Do not build yet:

- uncontrolled autonomous brokerage;
- auto-send;
- auto-submit;
- auto-sign;
- broad MLS/TRREB/REALM scraping;
- authenticated MLS access without exact scope;
- tenant screening automation without explicit review gates;
- payment, tax, banking, or ID workflows;
- general-purpose OpenClaw access to production data;
- experimental `stash@{0}` work unless Kevin explicitly approves.

## 7. Decision gates

Use these gates before each phase:

- Is SKC Agent OS the source of truth?
- Is the workflow used in real operations?
- Is the approval gate visible?
- Can Kevin override?
- Are blocked states explicit?
- Are audit notes preserved?
- Is sensitive data scoped?
- Does the workflow avoid auto-send, auto-submit, and auto-sign?
- Is the change isolated from experimental code?

If any answer is no, stop and tighten the scope.

## 8. Metrics to track

Track:

- workflows run per day;
- time saved;
- blocked count;
- top blocked reasons;
- override rate;
- draft quality;
- approval queue count;
- duplicate skipped count;
- missing data frequency;
- Kevin confidence rating;
- next fix candidate.

## 9. Success criteria

The 30-day phase succeeds if:

- Kevin uses SKC Agent OS daily;
- at least one workflow saves meaningful time every day;
- blockers are visible instead of silent;
- draft quality improves;
- the highest-friction workflow is fixed;
- source-of-truth memory is designed or started;
- Automation Engine v1 has a narrow, evidence-backed target;
- no auto-send, auto-submit, or uncontrolled autonomy is introduced.

## 10. Next-phase backlog

Backlog candidates:

- source-of-truth memory layer;
- workflow-specific approval queues;
- stronger blocked reason taxonomy;
- better Gmail draft review screen;
- better listing alert duplicate references;
- buyer/renter preference memory;
- paperwork deadline visibility;
- safe Codex Chrome browser evidence capture workflow;
- OpenClaw public-research import pattern;
- Automation Engine v1 for the highest-value preparation workflow;
- strategy coordination only after enough production evidence exists.
