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
