from datetime import datetime, timezone
from uuid import uuid4

from . import schemas


SAFETY_BOUNDARY = (
    "operator_review_only: the bridge prepares SKC context, OpenClaw handoffs, "
    "and Codex Chrome extension handoffs, but it does not send messages, submit "
    "forms, mutate CRM data, or modify OpenClaw workspaces."
)


def get_agent_bridge_status() -> schemas.AgentBridgeStatusResponse:
    """Return the product-level integration surfaces exposed by SKC Agent OS."""
    return schemas.AgentBridgeStatusResponse(
        product="SKC Agent OS / AI-CRM",
        mode="operator_review_only",
        bridge_status="ready_for_handoff",
        direct_external_actions=False,
        safety_boundary=SAFETY_BOUNDARY,
        capabilities=[
            schemas.AgentBridgeCapability(
                key="skc_agent_os",
                label="SKC Agent OS CRM Context",
                status="ready",
                product_surface="AI-CRM backend and frontend",
                description=(
                    "Collects client, property, workflow, and agent notes into a "
                    "single review package for downstream agent tools."
                ),
                guardrails=[
                    "No automatic CRM mutation from bridge sessions.",
                    "No credential or token storage.",
                    "Human review remains required before external action.",
                ],
                evidence=[
                    "Agent Bridge API is served under /api/integrations/agent-bridge.",
                    "Frontend bridge page consumes the API through crmService.",
                ],
                next_action="Create a bridge session from the Integrations page.",
            ),
            schemas.AgentBridgeCapability(
                key="openclaw",
                label="OpenClaw Scoped Agent Handoff",
                status="ready_for_handoff",
                product_surface="OpenClaw workspaces",
                description=(
                    "Turns SKC workflow context into a bounded OpenClaw prompt for "
                    "public research, local-file review, forms, or email-draft workspaces."
                ),
                guardrails=[
                    "Use explicit named OpenClaw agents and scoped workspaces.",
                    "No MLS/TRREB/REALM login or private data unless separately approved.",
                    "No OpenClaw workspace or config changes from SKC Agent OS.",
                ],
                evidence=[
                    "Handoff prompts include workspace boundary and approval language.",
                    "Bridge sessions do not execute OpenClaw commands.",
                ],
                next_action="Review the generated OpenClaw handoff before running it externally.",
            ),
            schemas.AgentBridgeCapability(
                key="codex_chrome_extension",
                label="Codex Chrome Extension Browser Handoff",
                status="ready_for_handoff",
                product_surface="Codex Chrome extension",
                description=(
                    "Turns SKC workflow context into browser-side instructions for "
                    "already-authorized tabs, visible listing evidence, and screenshot-backed review."
                ),
                guardrails=[
                    "Use only already-authorized browser sessions.",
                    "No sending, signing, posting, purchasing, or submitting without approval.",
                    "Keep visible evidence, filenames, listing IDs, and deadlines in the review.",
                ],
                evidence=[
                    "Chrome handoff prompts are generated as review-only instructions.",
                    "Bridge sessions preserve the human-review boundary.",
                ],
                next_action="Review the generated Chrome extension handoff before using it in browser.",
            ),
        ],
    )


def create_agent_bridge_session(
    request: schemas.AgentBridgeSessionRequest,
) -> schemas.AgentBridgeSessionResponse:
    created_at = datetime.now(timezone.utc)
    session_id = f"bridge-{created_at.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    summary = _summarize_request(request)

    handoffs: list[schemas.AgentBridgeHandoff] = []
    if request.include_openclaw:
        handoffs.append(_build_openclaw_handoff(request, summary))
    if request.include_codex_chrome:
        handoffs.append(_build_chrome_handoff(request, summary))

    if not handoffs:
        handoffs.append(_build_skc_review_handoff(request, summary))

    approvals_required = [
        "Human review before sending emails, messages, offers, forms, or signature packages.",
        "Separate approval before using logged-in browser sessions or private client data.",
        "Separate approval before changing OpenClaw workspaces, configs, or clean baselines.",
    ]

    return schemas.AgentBridgeSessionResponse(
        session_id=session_id,
        status="waiting_operator_review",
        created_at=created_at,
        workflow=request.workflow,
        summary=summary,
        approvals_required=approvals_required,
        handoffs=handoffs,
        audit_notes=[
            "No external tool was executed by this API call.",
            "No Gmail draft, email send, browser submit, or OpenClaw mutation was performed.",
            "Use the generated handoff text as the reviewed bridge between SKC Agent OS and the external agent surface.",
        ],
    )


def _summarize_request(request: schemas.AgentBridgeSessionRequest) -> str:
    parts = [f"Workflow: {request.workflow.strip()}"]
    if request.client_name:
        parts.append(f"Client: {request.client_name.strip()}")
    if request.property_address:
        parts.append(f"Property: {request.property_address.strip()}")
    if request.requested_outcome:
        parts.append(f"Outcome: {request.requested_outcome.strip()}")
    parts.append(f"Context: {_compact_context(request.source_context)}")
    return " | ".join(parts)


def _compact_context(value: str) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= 240 else f"{cleaned[:237]}..."


def _build_openclaw_handoff(
    request: schemas.AgentBridgeSessionRequest,
    summary: str,
) -> schemas.AgentBridgeHandoff:
    prompt = f"""Use OpenClaw as a scoped SKC Agent OS handoff.

SKC bridge session:
{summary}

Rules:
- Use an explicit named OpenClaw agent/workspace that matches the task scope.
- Public browsing stays public-only: no MLS/TRREB/REALM login, no client-private data, no submissions.
- Local-file work requires exact file-path approval before reading files.
- Email/form work is draft-only and must not send or submit.
- Do not modify ~/.openclaw/openclaw.json, workspace rules, or clean baselines.

Return:
- Evidence gathered.
- Source handles, URLs, filenames, or visible listing IDs.
- Risks / needs confirmation.
- A concise next-step recommendation for human review.
"""
    return schemas.AgentBridgeHandoff(
        target="openclaw",
        target_label="OpenClaw scoped agent",
        status="ready_for_review",
        title="OpenClaw handoff package",
        instructions=[
            "Choose the smallest scoped OpenClaw workspace for the task.",
            "Run the handoff only after confirming it stays inside the approved scope.",
            "Bring results back into SKC Agent OS as evidence, not as an auto-approved action.",
        ],
        prompt=prompt,
        approval_required=True,
    )


def _build_chrome_handoff(
    request: schemas.AgentBridgeSessionRequest,
    summary: str,
) -> schemas.AgentBridgeHandoff:
    prompt = f"""Use the Codex Chrome extension as a browser-side SKC Agent OS handoff.

SKC bridge session:
{summary}

Browser rules:
- Use only tabs/sessions the operator has already opened and authorized.
- Keep visible evidence central: listing IDs, attachment names, floor plans, conditions, dates, screenshots, and source handles.
- Do not send, sign, submit, purchase, delete, or message externally.
- If login, permissions, or page state blocks verification, report the blocker directly.
- Separate facts from assumptions and flag items needing human confirmation.

Return:
- What was visible on-screen.
- What could not be verified.
- Relevant page handles or filenames.
- A short operator-ready recommendation.
"""
    return schemas.AgentBridgeHandoff(
        target="codex_chrome_extension",
        target_label="Codex Chrome extension",
        status="ready_for_review",
        title="Chrome extension handoff package",
        instructions=[
            "Open the already-authorized browser tab before using this handoff.",
            "Use the Chrome extension for inspection and evidence capture only.",
            "Return the browser evidence to SKC Agent OS for human review.",
        ],
        prompt=prompt,
        approval_required=True,
    )


def _build_skc_review_handoff(
    request: schemas.AgentBridgeSessionRequest,
    summary: str,
) -> schemas.AgentBridgeHandoff:
    prompt = f"""Review this SKC Agent OS bridge context without external tools.

SKC bridge session:
{summary}

Return a concise operator checklist and identify whether OpenClaw, the Codex Chrome extension, both, or neither should be used next.
"""
    return schemas.AgentBridgeHandoff(
        target="skc_agent_os",
        target_label="SKC Agent OS review",
        status="ready_for_review",
        title="Internal SKC review package",
        instructions=[
            "Review the CRM context before selecting an external tool.",
            "Keep client-facing action approval-gated.",
        ],
        prompt=prompt,
        approval_required=True,
    )
