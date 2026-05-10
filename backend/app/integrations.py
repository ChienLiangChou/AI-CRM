import json
import shlex
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from . import models, schemas


SAFETY_BOUNDARY = (
    "operator_review_only: the bridge prepares SKC context, OpenClaw handoffs, "
    "and Codex Chrome extension handoffs, but it does not send messages, submit "
    "forms, mutate CRM data, or modify OpenClaw workspaces."
)

OPENCLAW_PROFILES = {
    "standalone_sop": {
        "agent": "standalone",
        "workspace": "/Users/kevinchou/OpenClaw_Workspaces/openclaw-standalone",
        "label": "OpenClaw standalone SOP/workflow map",
        "rules": [
            "Use dummy examples only.",
            "Do not access client or tenant data.",
            "Do not send or submit anything.",
        ],
    },
    "browsertest_public_research": {
        "agent": "browsertest",
        "workspace": "/Users/kevinchou/OpenClaw_Workspaces/openclaw-browser-test",
        "label": "OpenClaw public-only browser research",
        "rules": [
            "No login.",
            "No MLS/TRREB/REALM.",
            "No client/private data.",
            "No downloads or external messaging.",
        ],
    },
    "formtest_dummy_listing_package": {
        "agent": "formtest",
        "workspace": "/Users/kevinchou/OpenClaw_Workspaces/openclaw-form-test",
        "label": "OpenClaw dummy listing package",
        "rules": [
            "Use fake data only.",
            "Do not submit forms.",
            "Do not access real accounts.",
        ],
    },
    "emaildrafttest_dummy_email": {
        "agent": "emaildrafttest",
        "workspace": "/Users/kevinchou/OpenClaw_Workspaces/openclaw-email-draft-test",
        "label": "OpenClaw dummy email draft",
        "rules": [
            "Use fake names and fake property details.",
            "Do not send, queue, or connect to email.",
            "Return draft text only.",
        ],
    },
    "localfilestest_one_file_summary": {
        "agent": "localfilestest",
        "workspace": "/Users/kevinchou/OpenClaw_Workspaces/openclaw-local-files-test",
        "label": "OpenClaw one-file summary",
        "rules": [
            "Use only one explicitly approved absolute file path.",
            "Do not read folders.",
            "Do not inspect neighboring files.",
        ],
    },
}

CHROME_PROFILES = {
    "skc_ui_test": {
        "label": "Codex Chrome SKC UI test",
        "rules": [
            "Inspect only the already-open SKC Agent OS page.",
            "Do not submit forms or change settings.",
            "Return visible result and blockers.",
        ],
    },
    "gmail_draft_check": {
        "label": "Codex Chrome Gmail draft check",
        "rules": [
            "Use only the already-authorized Gmail tab.",
            "Check draft existence only.",
            "Do not send, edit, delete, archive, label, or change account settings.",
        ],
    },
    "gmail_thread_summary": {
        "label": "Codex Chrome approved Gmail thread summary",
        "rules": [
            "Summarize only the explicitly approved open thread.",
            "Do not open other emails.",
            "Do not reply, forward, download, label, or archive.",
        ],
    },
    "listing_tab_comparison": {
        "label": "Codex Chrome already-open listing tab comparison",
        "rules": [
            "Compare only already-open listing tabs.",
            "Do not login, scrape broadly, or open new searches.",
            "Return visible listing facts and needs-confirmation notes.",
        ],
    },
}

SKC_INTERNAL_PROFILES = {
    "internal_review": {
        "label": "SKC Agent OS internal review",
        "rules": [
            "Review CRM context before choosing an external tool.",
            "Keep all client-facing action approval-gated.",
            "Return checklist and next recommended tool.",
        ],
    }
}


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


def create_agent_bridge_execution(
    db: Session,
    request: schemas.AgentBridgeExecutionCreateRequest,
) -> schemas.AgentBridgeExecutionResponse:
    profile = _resolve_profile(request.target, request.execution_profile)
    created_at = datetime.now(timezone.utc)
    run_id = f"exec-{created_at.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    session_request = schemas.AgentBridgeSessionRequest(
        workflow=request.workflow,
        source_context=request.source_context,
        client_name=request.client_name,
        property_address=request.property_address,
        requested_outcome=request.requested_outcome,
        include_openclaw=request.target == "openclaw",
        include_codex_chrome=request.target == "codex_chrome_extension",
    )
    summary = _summarize_request(session_request)
    handoff = _build_target_handoff(request.target, session_request, summary)
    package = _build_execution_package(request, profile, handoff.prompt, summary)
    command_text = _build_command_text(request.target, profile, handoff.prompt)
    approved_at = created_at if request.approved_by_kevin else None
    status = "ready_for_external_runner" if request.approved_by_kevin else "waiting_kevin_approval"

    audit_notes = [
        "Execution ticket created inside SKC Agent OS.",
        "No email, browser submit, signature action, account mutation, or OpenClaw command was executed by ticket creation.",
        "External execution requires Kevin approval and the generated bounded execution package.",
    ]
    if request.approved_by_kevin:
        audit_notes.append("Kevin approval was marked as confirmed by the operator.")

    db_run = models.AgentBridgeRun(
        run_id=run_id,
        target=request.target,
        target_label=profile["label"],
        execution_profile=request.execution_profile or _default_profile(request.target),
        workflow=request.workflow,
        status=status,
        client_name=request.client_name,
        property_address=request.property_address,
        requested_outcome=request.requested_outcome,
        source_context=request.source_context,
        summary=summary,
        handoff_prompt=handoff.prompt,
        execution_package=json.dumps(package),
        command_text=command_text,
        audit_notes=json.dumps(audit_notes),
        approval_required=1,
        approved_by_kevin=1 if request.approved_by_kevin else 0,
        approved_at=approved_at,
        operator_notes=request.operator_notes,
        result_payload="{}",
    )
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    return _run_to_response(db_run)


def list_agent_bridge_executions(db: Session) -> list[schemas.AgentBridgeExecutionResponse]:
    runs = (
        db.query(models.AgentBridgeRun)
        .order_by(models.AgentBridgeRun.created_at.desc())
        .limit(25)
        .all()
    )
    return [_run_to_response(run) for run in runs]


def approve_agent_bridge_execution(
    db: Session,
    run_id: str,
    request: schemas.AgentBridgeExecutionApproveRequest,
) -> schemas.AgentBridgeExecutionResponse | None:
    db_run = db.query(models.AgentBridgeRun).filter(models.AgentBridgeRun.run_id == run_id).first()
    if not db_run:
        return None
    if not request.approved_by_kevin:
        db_run.status = "waiting_kevin_approval"
        db_run.approved_by_kevin = 0
        db_run.approved_at = None
    else:
        db_run.status = "ready_for_external_runner"
        db_run.approved_by_kevin = 1
        db_run.approved_at = datetime.now(timezone.utc)

    db_run.operator_notes = request.operator_notes or db_run.operator_notes
    db_run.updated_at = datetime.utcnow()
    audit_notes = _json_loads_list(db_run.audit_notes)
    audit_notes.append(
        "Execution ticket approval updated. No external command, browser action, send, submit, or sign action was performed by this API call."
    )
    db_run.audit_notes = json.dumps(audit_notes)
    db.commit()
    db.refresh(db_run)
    return _run_to_response(db_run)


def record_agent_bridge_execution_result(
    db: Session,
    run_id: str,
    request: schemas.AgentBridgeExecutionResultRequest,
) -> schemas.AgentBridgeExecutionResponse | None:
    db_run = db.query(models.AgentBridgeRun).filter(models.AgentBridgeRun.run_id == run_id).first()
    if not db_run:
        return None
    db_run.status = request.status
    db_run.result_summary = request.result_summary
    db_run.result_payload = json.dumps(request.result_payload)
    db_run.updated_at = datetime.utcnow()
    audit_notes = _json_loads_list(db_run.audit_notes)
    audit_notes.append(
        "External tool result was recorded in SKC Agent OS for human review. Recording a result does not approve client-facing action."
    )
    db_run.audit_notes = json.dumps(audit_notes)
    db.commit()
    db.refresh(db_run)
    return _run_to_response(db_run)


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


def _resolve_profile(target: str, profile_name: str | None) -> dict:
    profile = profile_name or _default_profile(target)
    profiles = _profiles_for_target(target)
    if profile not in profiles:
        allowed = ", ".join(sorted(profiles))
        raise ValueError(f"Unsupported execution_profile '{profile}'. Allowed profiles: {allowed}")
    return profiles[profile]


def _default_profile(target: str) -> str:
    if target == "openclaw":
        return "browsertest_public_research"
    if target == "codex_chrome_extension":
        return "skc_ui_test"
    return "internal_review"


def _profiles_for_target(target: str) -> dict:
    if target == "openclaw":
        return OPENCLAW_PROFILES
    if target == "codex_chrome_extension":
        return CHROME_PROFILES
    return SKC_INTERNAL_PROFILES


def _build_target_handoff(
    target: str,
    request: schemas.AgentBridgeSessionRequest,
    summary: str,
) -> schemas.AgentBridgeHandoff:
    if target == "openclaw":
        return _build_openclaw_handoff(request, summary)
    if target == "codex_chrome_extension":
        return _build_chrome_handoff(request, summary)
    return _build_skc_review_handoff(request, summary)


def _build_execution_package(
    request: schemas.AgentBridgeExecutionCreateRequest,
    profile: dict,
    prompt: str,
    summary: str,
) -> dict:
    return {
        "target": request.target,
        "target_label": profile["label"],
        "execution_profile": request.execution_profile or _default_profile(request.target),
        "workflow": request.workflow,
        "summary": summary,
        "approval_required": True,
        "approved_by_kevin": request.approved_by_kevin,
        "operator_notes": request.operator_notes,
        "safety_boundary": SAFETY_BOUNDARY,
        "rules": profile["rules"],
        "handoff_prompt": prompt,
        "result_contract": [
            "Return evidence gathered.",
            "Return blockers and what could not be verified.",
            "Return source handles, URLs, filenames, or visible page/listing IDs where available.",
            "Return recommendation for Kevin review only.",
        ],
    }


def _build_command_text(target: str, profile: dict, prompt: str) -> str | None:
    if target == "openclaw":
        quoted_prompt = shlex.quote(prompt)
        workspace = shlex.quote(profile["workspace"])
        agent = shlex.quote(profile["agent"])
        return f"cd {workspace} && openclaw run --agent {agent} --task {quoted_prompt}"
    if target == "codex_chrome_extension":
        return f"Codex Chrome supervised prompt:\n\n{prompt}"
    return None


def _run_to_response(run: models.AgentBridgeRun) -> schemas.AgentBridgeExecutionResponse:
    return schemas.AgentBridgeExecutionResponse(
        run_id=run.run_id,
        target=run.target,
        target_label=run.target_label,
        execution_profile=run.execution_profile,
        status=run.status,
        workflow=run.workflow,
        summary=run.summary,
        safety_boundary=SAFETY_BOUNDARY,
        approval_required=bool(run.approval_required),
        approved_by_kevin=bool(run.approved_by_kevin),
        created_at=run.created_at,
        updated_at=run.updated_at,
        approved_at=run.approved_at,
        handoff_prompt=run.handoff_prompt,
        execution_package=_json_loads_dict(run.execution_package),
        command_text=run.command_text,
        audit_notes=_json_loads_list(run.audit_notes),
        result_summary=run.result_summary,
        result_payload=_json_loads_dict(run.result_payload),
    )


def _json_loads_dict(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _json_loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


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
