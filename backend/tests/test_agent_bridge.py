from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_bridge_status_exposes_all_surfaces():
    response = client.get("/api/integrations/agent-bridge/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bridge_status"] == "ready_for_handoff"
    assert payload["direct_external_actions"] is False

    capability_keys = {item["key"] for item in payload["capabilities"]}
    assert capability_keys == {
        "skc_agent_os",
        "openclaw",
        "codex_chrome_extension",
    }


def test_agent_bridge_session_builds_review_only_handoffs():
    response = client.post(
        "/api/integrations/agent-bridge/sessions",
        json={
            "workflow": "seller_listing_safety",
            "client_name": "Kevin Test",
            "property_address": "25 Capreol Court #1007",
            "requested_outcome": "Prepare a safe listing-readiness review.",
            "source_context": "Compare visible listing evidence, attachments, and browser-side facts before any external action.",
            "include_openclaw": True,
            "include_codex_chrome": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "waiting_operator_review"
    assert payload["workflow"] == "seller_listing_safety"
    assert payload["approvals_required"]
    assert any("No external tool was executed" in note for note in payload["audit_notes"])

    handoff_targets = {item["target"] for item in payload["handoffs"]}
    assert handoff_targets == {"openclaw", "codex_chrome_extension"}

    prompts = "\n".join(item["prompt"] for item in payload["handoffs"])
    assert "25 Capreol Court #1007" in prompts
    assert "Do not send" in prompts or "must not send" in prompts
    assert "Do not modify ~/.openclaw/openclaw.json" in prompts


def test_agent_bridge_session_can_stay_internal_only():
    response = client.post(
        "/api/integrations/agent-bridge/sessions",
        json={
            "workflow": "triage",
            "source_context": "Review a draft task and decide which integration should be used next.",
            "include_openclaw": False,
            "include_codex_chrome": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [handoff["target"] for handoff in payload["handoffs"]] == ["skc_agent_os"]
    assert payload["handoffs"][0]["approval_required"] is True


def test_agent_bridge_execution_creates_openclaw_ticket_without_running_command():
    response = client.post(
        "/api/integrations/agent-bridge/executions",
        json={
            "target": "openclaw",
            "workflow": "public_research",
            "execution_profile": "browsertest_public_research",
            "source_context": "Prepare public-only research for a dummy seller listing readiness checklist.",
            "requested_outcome": "Return source links and risks for Kevin review.",
            "approved_by_kevin": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "openclaw"
    assert payload["status"] == "waiting_kevin_approval"
    assert payload["approval_required"] is True
    assert payload["approved_by_kevin"] is False
    assert "openclaw run --agent browsertest" in payload["command_text"]
    assert "No email, browser submit, signature action" in " ".join(payload["audit_notes"])
    assert "No MLS/TRREB/REALM" in " ".join(payload["execution_package"]["rules"])


def test_agent_bridge_execution_approve_and_record_result():
    created = client.post(
        "/api/integrations/agent-bridge/executions",
        json={
            "target": "codex_chrome_extension",
            "workflow": "ui_check",
            "execution_profile": "skc_ui_test",
            "source_context": "Check the already-open SKC Agent OS Agent Bridge page.",
            "approved_by_kevin": False,
        },
    ).json()

    approved = client.post(
        f"/api/integrations/agent-bridge/executions/{created['run_id']}/approve",
        json={"approved_by_kevin": True, "operator_notes": "Kevin approved UI check scope."},
    )

    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["status"] == "ready_for_external_runner"
    assert approved_payload["approved_by_kevin"] is True
    assert approved_payload["command_text"].startswith("Codex Chrome supervised prompt:")

    result = client.post(
        f"/api/integrations/agent-bridge/executions/{created['run_id']}/result",
        json={
            "status": "completed",
            "result_summary": "Agent Bridge page was visible and review-gated.",
            "result_payload": {"visible_page": "Agent Bridge", "external_action_taken": False},
        },
    )

    assert result.status_code == 200
    result_payload = result.json()
    assert result_payload["status"] == "completed"
    assert result_payload["result_summary"] == "Agent Bridge page was visible and review-gated."
    assert result_payload["result_payload"]["external_action_taken"] is False


def test_agent_bridge_execution_rejects_wrong_profile_for_target():
    response = client.post(
        "/api/integrations/agent-bridge/executions",
        json={
            "target": "codex_chrome_extension",
            "workflow": "bad_profile",
            "execution_profile": "browsertest_public_research",
            "source_context": "This should be rejected because the profile belongs to OpenClaw.",
        },
    )

    assert response.status_code == 400
    assert "Unsupported execution_profile" in response.json()["detail"]
