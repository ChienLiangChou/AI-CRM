# SKC 20X First Week Usage Checklist

## 1. Goal of first week

Kevin should start using SKC Agent OS now instead of waiting for every future module to be fully built.

The goal is not perfection. The goal is to collect real friction data:

- what saves time;
- what blocks progress;
- what draft quality is good enough;
- where Kevin overrides the system;
- which workflow deserves the next build phase.

## 2. Daily 5-10 minute routine

Every day:

1. Open SKC Agent OS.
2. Review the highest-priority workflow queue.
3. Run one or more approved v1 workflows.
4. Review AI-prepared drafts, matches, checklists, or recommendations.
5. Approve nothing automatically.
6. Record one short friction log entry.
7. Pick one next fix candidate.

## 3. Which modules to run daily

Use these first:

- Listing Alert Recommendation Workflow v1;
- Follow-up Agent v1;
- Client Conversation Closer Agent v1;
- Buyer Match Agent v1;
- Transaction Paperwork v1;
- Operations / Compliance Visibility Module v1.

Do not start with experimental modules unless Kevin explicitly chooses that day's experiment.

## 4. What to record

Record:

- workflow used;
- outcome type;
- blocked reason;
- whether Kevin overrode the recommendation;
- draft quality;
- time saved;
- one sentence insight;
- next fix candidate.

Use the same lightweight template every day.

## 5. Listing Alert Automatic Mode checklist

For each listing alert:

- Confirm Gmail intake source.
- Confirm REALM/listing email extraction.
- Confirm client match.
- Confirm whether status is blocked, waiting approval, duplicate skipped, or ready for review.
- Review recommendation rationale.
- Review Gmail draft if created.
- Do not send automatically.
- Record blocker or override.

## 6. Conversation Closer checklist

For each conversation closer run:

- Confirm client context.
- Confirm the conversation goal.
- Review suggested closing language.
- Check tone and risk.
- Rewrite if needed.
- Do not send automatically.
- Record whether the draft was usable.

## 7. Buyer Match checklist

For each buyer/renter match:

- Confirm client budget.
- Confirm areas.
- Confirm must-haves and deal breakers.
- Review ranked matches.
- Check missing facts.
- Record whether the match was accurate enough for Kevin review.
- Do not send recommendations automatically.

## 8. Transaction Paperwork checklist

For each paperwork review:

- Confirm transaction identity.
- Confirm document list.
- Confirm missing signatures, dates, fields, and deadlines.
- Confirm Schedule B/C or condition issues if relevant.
- Prepare checklist only.
- Do not edit contracts.
- Do not send signature packages.

## 9. Ops Visibility checklist

For operations/compliance visibility:

- Review current open items.
- Check blocked workflows.
- Check approval queues.
- Check stale runs.
- Check duplicate skipped references.
- Record the highest operational risk.

## 10. What not to automate this week

Do not automate:

- sending;
- signing;
- form submission;
- pricing judgment;
- negotiation decisions;
- tenant screening decisions;
- legal/compliance-sensitive decisions;
- MLS/TRREB/REALM login automation;
- OpenClaw use on real client/tenant data;
- experimental stash work.

## 11. Friction log template

```text
Date:
Workflow used:
Outcome type:
Blocked reason:
Override used:
Draft quality:
Time saved:
1 sentence insight:
Next fix candidate:
```

Suggested values:

- Outcome type: prepared, waiting approval, blocked, duplicate skipped, not useful.
- Override used: yes, no, partial.
- Draft quality: ready, minor edit, major edit, unusable.
- Time saved: 0 min, 5 min, 15 min, 30 min, 60+ min.

## 12. End-of-week review questions

At the end of week 1, answer:

1. Which workflow saved the most time?
2. Which workflow blocked most often?
3. Which workflow had the best draft quality?
4. Which workflow required the most Kevin overrides?
5. Which missing data appeared repeatedly?
6. Which step still feels manual but safe to automate?
7. Which step is high-risk and must stay human-reviewed?

## 13. How to decide the next build phase

Choose the next build phase based on evidence, not excitement.

Prioritize a workflow if:

- it is used daily or almost daily;
- it has repeated blockers;
- it saves meaningful time when it works;
- it has clear source-of-truth data;
- it can remain approval-gated;
- it does not require auto-send, auto-submit, or uncontrolled autonomy.

Do not build Automation Engine v1 until real first-week friction data shows which workflow should be automated first.
