import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path("/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/check_watchlists.py")
REVIEW_SCRIPT_PATH = Path("/Users/kevinchou/.codex/automations/skc-crm-watchlist-check/review_watchlist_alert.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("skc_watchlist_check_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_review_script_module():
    spec = importlib.util.spec_from_file_location("skc_watchlist_review_script", REVIEW_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_write_summary_artifact_persists_latest_json(tmp_path):
    script = load_script_module()
    target = tmp_path / "artifacts" / "latest-summary.json"

    written = script.write_summary_artifact(
        {"ok": True, "check_result": {"created_alerts": 2}},
        target,
    )

    assert written == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["check_result"]["created_alerts"] == 2
    assert payload["artifact_path"] == str(target)
    assert payload["artifact_written_at"]


def test_attach_codex_notification_summary_persists_mobile_summary(tmp_path):
    script = load_script_module()
    target = tmp_path / "artifacts" / "latest-summary.json"
    result = {
        "ok": True,
        "check_result": {"checked": 0, "created_alerts": 0, "active_count": 1, "due_count": 0},
        "property_source": {"properties_count": 0, "csv_drop_folder_pending_count": 0},
        "readiness_report": {"overall_status": "blocked", "next_actions": ["Import authorized REALM/TRREB rows."]},
        "delivery_gates": {"ready_count": 0, "active_count": 1, "items": []},
        "launch_action_pack": {"missing_email_count": 0, "auto_send_server_enabled": False},
        "csv_drop_import": {"message": "CSV drop-folder processed 0 new file(s)."},
        "gmail_feed_import": {"enabled": False},
        "source_tasks": {"tasks": []},
        "notification_logs": [],
    }

    summary = script.attach_codex_notification_summary(result)
    script.write_summary_artifact(result, target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["codex_notification_summary"] == summary
    assert summary.startswith("SKC CRM Watchlist 通知")
    assert "Import authorized REALM/TRREB rows." in summary
    assert "不直接寄 Gmail" in summary


def test_csv_drop_folder_imports_new_csv_once_and_tracks_hash(tmp_path, monkeypatch):
    script = load_script_module()
    drop_dir = tmp_path / "drop"
    state_path = tmp_path / "state.json"
    drop_dir.mkdir()
    csv_path = drop_dir / "realm-export.csv"
    csv_path.write_text(
        "mls_number,street,city,status,property_type,list price,beds,baths,parking\n"
        "N100001,109 Brownstone Circle,Thornhill,For Sale,Townhouse,1199000,3,3,1\n",
        encoding="utf-8",
    )
    calls = []

    def fake_import(path, csv_file, dry_run=False):
        calls.append((path, csv_file.name, dry_run))
        return {
            "success": True,
            "message": "Imported 1 new and 0 updated property row(s).",
            "created": 1,
            "updated": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(script, "api_multipart_csv", fake_import)

    first = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)
    second = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)

    assert calls == [("/properties/import-csv", "realm-export.csv", False)]
    assert len(first["imported"]) == 1
    assert first["skipped"] == []
    assert first["failed"] == []
    assert second["imported"] == []
    assert len(second["skipped"]) == 1
    assert second["skipped"][0]["reason"] == "already_imported"
    assert state_path.exists()


def test_drop_folder_imports_reso_json_once_and_tracks_hash(tmp_path, monkeypatch):
    script = load_script_module()
    drop_dir = tmp_path / "drop"
    state_path = tmp_path / "state.json"
    drop_dir.mkdir()
    json_path = drop_dir / "realm-reso-export.json"
    json_path.write_text(
        '{"value":[{"ListingKey":"N100001","UnparsedAddress":"109 Brownstone Circle, Thornhill, ON"}]}',
        encoding="utf-8",
    )
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {
            "success": True,
            "message": "Imported 1 new and 0 updated property row(s) from RESO/MLS JSON.",
            "created": 1,
            "updated": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(script, "api_json", fake_api_json)

    first = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)
    second = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)

    assert calls == [
        (
            "/properties/import-reso-json",
            "POST",
            {
                "data": {
                    "value": [
                        {
                            "ListingKey": "N100001",
                            "UnparsedAddress": "109 Brownstone Circle, Thornhill, ON",
                        }
                    ]
                },
                "dry_run": False,
            },
        )
    ]
    assert len(first["imported"]) == 1
    assert first["imported"][0]["file"] == str(json_path)
    assert first["failed"] == []
    assert second["imported"] == []
    assert len(second["skipped"]) == 1
    assert second["skipped"][0]["reason"] == "already_imported"
    state = script.read_json_file(state_path, {})
    assert next(iter(state["hashes"].values()))["source_type"] == "reso_json"


def test_csv_drop_folder_imports_completed_source_csv_from_subfolders(tmp_path, monkeypatch):
    script = load_script_module()
    drop_dir = tmp_path / "drop"
    state_path = tmp_path / "state.json"
    source_dir = drop_dir / "source-templates"
    source_dir.mkdir(parents=True)
    (source_dir / "1-tom-lin.template.csv.disabled").write_text(
        "mls_number,street,city,status,property_type,list price,remarks\n"
        "TEMPLATE_ONLY_1,REPLACE_WITH_REALM_STREET,REPLACE_WITH_CITY,For Sale,Townhouse,REPLACE_WITH_LIST_PRICE,TEMPLATE ONLY\n",
        encoding="utf-8",
    )
    completed_csv = source_dir / "1-tom-lin.csv"
    completed_csv.write_text(
        "mls_number,street,city,status,property_type,list price,beds,baths,parking\n"
        "N100001,109 Brownstone Circle,Thornhill,For Sale,Townhouse,1199000,3,3,1\n",
        encoding="utf-8",
    )
    calls = []

    def fake_import(path, csv_file, dry_run=False):
        calls.append((path, str(csv_file.relative_to(drop_dir)), dry_run))
        return {
            "success": True,
            "message": "Imported 1 new and 0 updated property row(s).",
            "created": 1,
            "updated": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(script, "api_multipart_csv", fake_import)

    result = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)

    assert calls == [("/properties/import-csv", "source-templates/1-tom-lin.csv", False)]
    assert len(result["imported"]) == 1
    assert result["failed"] == []
    assert result["skipped"] == []
    assert state_path.exists()


def test_csv_drop_folder_rejected_csv_needs_attention_without_tracking_hash(tmp_path, monkeypatch):
    script = load_script_module()
    drop_dir = tmp_path / "drop"
    state_path = tmp_path / "state.json"
    drop_dir.mkdir()
    csv_path = drop_dir / "skc-watchlist-source-template.csv"
    csv_path.write_text(
        "mls_number,street,city,status,property_type,list price,remarks\n"
        "TEMPLATE_ONLY_1,REPLACE_WITH_REALM_STREET,REPLACE_WITH_CITY,For Sale,Townhouse,REPLACE_WITH_LIST_PRICE,TEMPLATE ONLY\n",
        encoding="utf-8",
    )
    calls = []

    def fake_import(path, csv_file, dry_run=False):
        calls.append((path, csv_file.name, dry_run))
        return {
            "success": False,
            "message": "Imported 0 new and 0 updated property row(s).",
            "created": 0,
            "updated": 0,
            "skipped": 1,
            "errors": ["row_2: template placeholder row skipped"],
        }

    monkeypatch.setattr(script, "api_multipart_csv", fake_import)

    first = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)
    second = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)

    assert calls == [
        ("/properties/import-csv", "skc-watchlist-source-template.csv", False),
        ("/properties/import-csv", "skc-watchlist-source-template.csv", False),
    ]
    assert first["imported"] == []
    assert first["skipped"] == []
    assert len(first["failed"]) == 1
    assert first["failed"][0]["reason"] == "import_rejected"
    assert "need attention" in first["message"]
    assert second["imported"] == []
    assert len(second["failed"]) == 1
    assert not state_path.exists()


def test_csv_drop_folder_can_be_disabled(tmp_path, monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_CSV_DROP_IMPORT_ENABLED", "false")

    result = script.import_csv_drop_folder(drop_dir=tmp_path / "drop", state_path=tmp_path / "state.json")

    assert result["enabled"] is False
    assert result["imported"] == []
    assert result["skipped"] == []
    assert result["failed"] == []


def test_watchlist_helper_files_write_next_actions_and_disabled_email_template(tmp_path, monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_HELPER_FILES_ENABLED", "true")
    drop_dir = tmp_path / "drop"

    result = script.write_watchlist_helper_files(
        drop_dir=drop_dir,
        delivery_gates={
            "items": [
                {
                    "contact_id": 7,
                    "watchlist_id": 3,
                    "contact_name": "Tom Lin",
                    "watchlist_name": "Tom seller watch",
                    "contact_email_present": False,
                    "action_required": "Add Tom Lin's client email.",
                }
            ]
        },
        source_tasks={
            "tasks": [
                {
                    "contact_id": 7,
                    "watchlist_id": 3,
                    "contact_name": "Tom Lin",
                    "watchlist_name": "Tom seller watch",
                    "priority": "source_required",
                    "client_email_needed": True,
                    "source_ready": False,
                    "required_statuses": ["listed_for_sale", "sold"],
                    "missing_required_statuses": ["listed_for_sale", "sold"],
                    "saved_search_name": "SKC Tom Lin - Seller Active + Sold Comps",
                    "gmail_query": "newer_than:14d Thornhill townhouse",
                    "steps": ["Export rows for: listed for sale, sold."],
                },
                {
                    "contact_id": 8,
                    "watchlist_id": 4,
                    "contact_name": "Amy Yuen",
                    "watchlist_name": "Amy buyer watch",
                    "priority": "ready",
                    "client_email_needed": False,
                    "source_ready": True,
                    "required_statuses": ["listed_for_sale"],
                    "missing_required_statuses": [],
                    "saved_search_name": "SKC Amy Yuen - Buyer Active Listings",
                    "gmail_query": "newer_than:14d Halton Hills detached",
                    "steps": ["Source rows are present."],
                },
            ]
        },
        launch_action_pack={
            "summary": "blocked: 1/2 watchlists ready.",
            "next_actions": ["Import authorized REALM/TRREB rows."],
            "preflight_checks": [
                {
                    "label": "Authorized Source Data",
                    "status": "blocked",
                    "detail": "Tom Lin still needs sold comps.",
                    "next_step": "Export authorized REALM/TRREB CSV rows.",
                }
            ],
            "items": [
                {
                    "contact_name": "Tom Lin",
                    "watchlist_name": "Tom seller watch",
                    "actions": ["Fill Tom Lin's client_email."],
                }
            ],
        },
        data_intake_checklist={"message": "Data intake blocked."},
        property_source={"properties_count": 0, "csv_drop_folder_pending_count": 0},
        csv_drop_import={"message": "CSV drop-folder processed 0 new file(s)."},
        gmail_feed_import={"enabled": False},
        source_setups=[
            {
                "watchlist_id": 3,
                "contact_id": 7,
                "contact_name": "Tom Lin",
                "watchlist_name": "Tom seller watch",
                "watch_type": "seller_listing_and_sold",
                "required_statuses": ["listed_for_sale", "sold"],
                "export_statuses": ["listed_for_sale", "sold"],
                "csv_columns": [
                    "mls_number",
                    "street",
                    "city",
                    "community",
                    "status",
                    "property_type",
                    "list price",
                    "sold price",
                    "rent",
                    "beds",
                    "baths",
                    "parking",
                    "url",
                    "remarks",
                ],
                "saved_search_name": "SKC Tom Lin - Seller Active + Sold Comps",
                "gmail_query": "newer_than:14d Thornhill townhouse",
                "realm_criteria": ["Area/community/city: Thornhill", "Property type: townhouse"],
                "realm_steps": ["Create or update the saved search.", "Export authorized rows."],
                "recommended_method": "Use authorized REALM/TRREB CSV exports first.",
                "next_actions": ["Preview CSV before import."],
            }
        ],
    )

    next_actions_path = drop_dir / "watchlist-next-actions.md"
    email_template_path = drop_dir / "client-email-tasks.template.csv.disabled"
    gmail_setup_path = drop_dir / "gmail-saved-search-feed-setup.txt"
    saved_search_path = drop_dir / "saved-searches" / "3-tom-lin.txt"
    source_template_path = drop_dir / "source-templates" / "3-tom-lin.template.csv.disabled"
    reso_template_path = drop_dir / "source-templates" / "3-tom-lin.template.json.disabled"

    assert result["enabled"] is True
    assert result["errors"] == []
    assert next_actions_path.exists()
    assert email_template_path.exists()
    assert gmail_setup_path.exists()
    assert saved_search_path.exists()
    assert source_template_path.exists()
    assert reso_template_path.exists()
    assert not (drop_dir / "client-email-tasks.csv").exists()
    assert all(item["importable_csv"] is False for item in result["files"])
    assert "Do not scrape MLS pages" in next_actions_path.read_text(encoding="utf-8")
    assert "Import authorized REALM/TRREB rows." in next_actions_path.read_text(encoding="utf-8")
    assert "saved-searches/*.txt" in next_actions_path.read_text(encoding="utf-8")
    assert "source-templates/*.template.csv.disabled" in next_actions_path.read_text(encoding="utf-8")
    assert "source-templates/*.template.json.disabled" in next_actions_path.read_text(encoding="utf-8")
    assert "gmail-saved-search-feed-setup.txt" in next_actions_path.read_text(encoding="utf-8")
    gmail_setup = gmail_setup_path.read_text(encoding="utf-8")
    assert "Gmail Saved-Search Feed Setup" in gmail_setup
    assert "READ GMAIL" in gmail_setup
    assert "Do not scrape MLS/REALM/TRREB pages" in gmail_setup
    assert "SKC Tom Lin - Seller Active + Sold Comps" in gmail_setup
    email_template = email_template_path.read_text(encoding="utf-8")
    assert "contact_id,contact_name,client_email,watchlist_id,watchlist_name,reason" in email_template
    assert "7,Tom Lin,,3,Tom seller watch" in email_template
    saved_search = saved_search_path.read_text(encoding="utf-8")
    assert "SKC Tom Lin - Seller Active + Sold Comps" in saved_search
    assert "newer_than:14d Thornhill townhouse" in saved_search
    source_template = source_template_path.read_text(encoding="utf-8")
    reso_template = json.loads(reso_template_path.read_text(encoding="utf-8"))
    assert "TEMPLATE_ONLY_TOM_LIN_1" in source_template
    assert "For Sale" in source_template
    assert "Sold" in source_template
    assert "value" in reso_template
    assert reso_template["value"][0]["PublicRemarks"].startswith("TEMPLATE ONLY")


def test_disabled_email_helper_template_is_not_auto_imported_as_csv(tmp_path, monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_HELPER_FILES_ENABLED", "true")
    drop_dir = tmp_path / "drop"
    state_path = tmp_path / "state.json"

    script.write_watchlist_helper_files(
        drop_dir=drop_dir,
        delivery_gates={"items": [{"contact_id": 7, "watchlist_id": 3, "contact_name": "Tom Lin", "contact_email_present": False}]},
        source_tasks={"tasks": []},
        launch_action_pack={},
        data_intake_checklist={},
        property_source={},
        csv_drop_import={},
        gmail_feed_import={},
    )
    result = script.import_csv_drop_folder(drop_dir=drop_dir, state_path=state_path)

    assert result["imported"] == []
    assert result["failed"] == []
    assert result["skipped"] == []
    assert not state_path.exists()


def test_import_csv_file_routes_client_email_task_csv_to_contacts_api(tmp_path, monkeypatch):
    script = load_script_module()
    csv_path = tmp_path / "client-email-tasks.csv"
    csv_path.write_text(
        "contact_id,contact_name,client_email,watchlist_id,watchlist_name\n"
        "7,Tom Lin,tom.lin@example.com,1,Tom Watch\n",
        encoding="utf-8",
    )
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if method == "GET":
            return {"id": 7, "name": "Tom Lin", "email": None}
        if method == "PUT":
            return {"id": 7, "name": "Tom Lin", "email": payload["email"]}
        raise AssertionError(method)

    def fake_property_import(*_args, **_kwargs):
        raise AssertionError("client-email-tasks.csv must not be imported as a property CSV")

    monkeypatch.setattr(script, "api_json", fake_api_json)
    monkeypatch.setattr(script, "api_multipart_csv", fake_property_import)

    result = script.import_csv_file(csv_path)

    assert result["updated"] == 1
    assert result["created"] == 0
    assert calls == [
        ("/contacts/7", "GET", None),
        ("/contacts/7", "PUT", {"email": "tom.lin@example.com"}),
    ]


def test_contact_email_task_csv_does_not_overwrite_different_existing_email(tmp_path, monkeypatch):
    script = load_script_module()
    csv_path = tmp_path / "client-email-tasks.csv"
    csv_path.write_text(
        "contact_id,contact_name,client_email\n"
        "7,Tom Lin,new@example.com\n",
        encoding="utf-8",
    )
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {"id": 7, "name": "Tom Lin", "email": "old@example.com"}

    monkeypatch.setattr(script, "api_json", fake_api_json)

    result = script.import_csv_file(csv_path)

    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert "already has a different email" in result["warnings"][0]
    assert calls == [("/contacts/7", "GET", None)]


def test_gmail_feed_import_uses_global_and_watchlist_queries(monkeypatch):
    script = load_script_module()
    monkeypatch.delenv("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED", raising=False)
    monkeypatch.delenv("WATCHLIST_GMAIL_FEED_QUERY", raising=False)
    monkeypatch.delenv("WATCHLIST_GMAIL_FEED_MAX_RESULTS", raising=False)
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {
            "success": True,
            "message": f"Imported {payload['query']}",
            "created": 1,
            "updated": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(script, "api_json", fake_api_json)

    result = script.import_gmail_saved_search_feeds(
        {
            "gmail_feed_enabled": True,
            "gmail_query": "global query",
            "gmail_max_results": 7,
        },
        [
            {"id": 1, "name": "Tom watch", "contact_name": "Tom Lin", "source_query": "tom query"},
            {"id": 2, "name": "Amy watch", "contact_name": "Amy Yuen", "source_query": "amy query"},
            {"id": 3, "name": "Duplicate watch", "contact_name": "Copy", "source_query": "tom query"},
            {"id": 4, "name": "Blank watch", "contact_name": "Blank", "source_query": ""},
        ],
    )

    assert result["enabled"] is True
    assert result["enabled_source"] == "crm_config"
    assert result["watchlist_query_count"] == 2
    assert result["global_query_count"] == 1
    assert result["message"].startswith("Processed 3 Gmail listing feed queries")
    assert [call[0] for call in calls] == ["/properties/import-gmail-feed"] * 3
    assert [call[2]["query"] for call in calls] == ["global query", "tom query", "amy query"]
    assert all(call[1] == "POST" for call in calls)
    assert all(call[2]["max_results"] == 7 for call in calls)
    assert [item["scope"] for item in result["imports"]] == ["global", "watchlist", "watchlist"]
    assert result["imports"][1]["contact_name"] == "Tom Lin"


def test_gmail_feed_import_can_be_enabled_by_env_without_crm_config(monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED", "true")
    monkeypatch.setenv("WATCHLIST_GMAIL_FEED_QUERY", "env global query")
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append(payload)
        return {"success": True, "message": "ok", "created": 0, "updated": 0, "skipped": 0}

    monkeypatch.setattr(script, "api_json", fake_api_json)

    result = script.import_gmail_saved_search_feeds(
        {"gmail_feed_enabled": False, "gmail_query": "crm query", "gmail_max_results": 10},
        [{"id": 1, "name": "Tom watch", "contact_name": "Tom Lin", "source_query": "tom query"}],
    )

    assert result["enabled"] is True
    assert result["enabled_source"] == "env"
    assert [call["query"] for call in calls] == ["env global query", "tom query"]
    assert all(call["gmail_read_confirmation"] == "READ GMAIL" for call in calls)


def test_gmail_feed_import_records_query_failures_without_stopping(monkeypatch):
    script = load_script_module()
    monkeypatch.delenv("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED", raising=False)
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append(payload["query"])
        if payload["query"] == "unsafe query":
            raise RuntimeError("POST /properties/import-gmail-feed failed: HTTP 400: gmail_feed_query_requires_recency")
        return {"success": True, "message": "ok", "created": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(script, "api_json", fake_api_json)

    result = script.import_gmail_saved_search_feeds(
        {
            "gmail_feed_enabled": True,
            "gmail_query": "unsafe query",
            "gmail_max_results": 10,
        },
        [
            {
                "id": 1,
                "name": "Tom watch",
                "contact_name": "Tom Lin",
                "source_query": "newer_than:14d REALM Thornhill listing",
            }
        ],
    )

    assert result["enabled"] is True
    assert result["success"] is True
    assert calls == ["unsafe query", "newer_than:14d REALM Thornhill listing"]
    assert result["imports"][0]["result"]["success"] is False
    assert "gmail_feed_query_requires_recency" in result["imports"][0]["result"]["errors"][0]
    assert result["imports"][1]["result"]["created"] == 1


def test_reso_connector_import_is_disabled_by_default(tmp_path, monkeypatch):
    script = load_script_module()
    monkeypatch.setattr(script, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("WATCHLIST_RESO_CONNECTOR_ENABLED", raising=False)
    monkeypatch.delenv("WATCHLIST_RESO_CONNECTOR_URL", raising=False)

    result = script.import_reso_connector_feed()

    assert result["enabled"] is False
    assert result["success"] is False
    assert result["endpoint"] is None
    assert "disabled" in result["message"]


def test_reso_connector_import_fetches_and_routes_json_to_crm_api(monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_ENABLED", "true")
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_URL", "https://reso.example.test/odata/Property?$top=25&token=secret")
    calls = []

    monkeypatch.setattr(
        script,
        "fetch_reso_connector_payload",
        lambda: {"value": [{"ListingKey": "N100001", "UnparsedAddress": "107 Brownstone Circle"}]},
    )

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {
            "success": True,
            "message": "Imported 1 new and 0 updated property row(s) from RESO/MLS JSON.",
            "created": 1,
            "updated": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(script, "api_json", fake_api_json)

    result = script.import_reso_connector_feed()

    assert result["enabled"] is True
    assert result["success"] is True
    assert result["endpoint"] == "https://reso.example.test/odata/Property?[redacted]"
    assert calls == [
        (
            "/properties/import-reso-json",
            "POST",
            {
                "data": {"value": [{"ListingKey": "N100001", "UnparsedAddress": "107 Brownstone Circle"}]},
                "dry_run": False,
            },
        )
    ]
    assert result["result"]["created"] == 1


def test_reso_connector_import_reports_fetch_failures_without_raising(monkeypatch):
    script = load_script_module()
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_ENABLED", "true")
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_URL", "https://reso.example.test/odata/Property?$top=25")

    def fail_fetch():
        raise RuntimeError("Cannot reach configured RESO connector endpoint.")

    monkeypatch.setattr(script, "fetch_reso_connector_payload", fail_fetch)

    result = script.import_reso_connector_feed()

    assert result["enabled"] is True
    assert result["success"] is False
    assert result["failed"] is True
    assert "Cannot reach configured RESO connector endpoint" in result["message"]
    assert result["endpoint"] == "https://reso.example.test/odata/Property?[redacted]"


def test_summarize_gmail_feed_import_item_includes_query_and_errors():
    script = load_script_module()

    summary = script.summarize_gmail_feed_import_item(
        {
            "contact_name": "Tom Lin",
            "query": "newer_than:14d Thornhill townhouse",
            "result": {
                "message": "No Gmail listing feed messages matched this query.",
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["gmail_feed_no_messages"],
            },
        }
    )

    assert "Tom Lin" in summary
    assert "No Gmail listing feed messages matched this query." in summary
    assert "errors=gmail_feed_no_messages" in summary
    assert "query=newer_than:14d Thornhill townhouse" in summary


def test_summarize_codex_notification_for_mobile_includes_review_packet():
    script = load_script_module()

    lines = script.summarize_codex_notification_for_mobile(
        {
            "alert_id": 42,
            "title": "Tom Lin: 2 watchlist update(s)",
            "body": "\n".join(
                [
                    "Property: 107 Brownstone Circle | Townhouse | $1,199,000",
                    "Why it matches: 比對分數 70，符合 Thornhill townhouse and price context.",
                    "Draft: Gmail draft created and waiting for Kevin review.",
                    "Freshness: Source date is today.",
                    "Source: REALM CSV.",
                    "Review in CRM: /watchlists?contact_id=7&alert_id=42&watchlist_id=3",
                    "Next: review the alert and draft before sending any client email.",
                ]
            ),
        }
    )

    joined = "\n".join(lines)
    assert "alert #42" in joined
    assert "Tom Lin: 2 watchlist update(s)" in joined
    assert "Property: 107 Brownstone Circle" in joined
    assert "Why it matches:" in joined
    assert "Gmail draft created and waiting for Kevin review" in joined
    assert "Review on Mac: http://127.0.0.1:5174/watchlists?contact_id=7&alert_id=42&watchlist_id=3" in joined
    assert "review_watchlist_alert.py list --action send" in joined
    assert "review_watchlist_alert.py send --alert-id 42 --confirm '沒有問題'" in joined


def test_review_script_blocks_send_without_explicit_confirmation(capsys):
    script = load_review_script_module()

    exit_code = script.send_reviewed_alert(42, confirmation=None, dry_run=True)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "requires Kevin's explicit review phrase" in captured.out


def test_review_script_list_mode_is_read_only_and_shows_next_commands(monkeypatch, capsys):
    script = load_review_script_module()
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        assert path == "/watchlist-alerts"
        assert method == "GET"
        return [
            {
                "id": 42,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin update",
                "status": "pending_review",
                "summary": "107 Brownstone Circle",
                "gmail_draft_id": None,
                "created_at": "2026-06-11T09:00:00",
            },
            {
                "id": 43,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin draft ready",
                "status": "draft_created",
                "summary": "109 Brownstone Circle",
                "gmail_draft_id": "draft-123",
                "created_at": "2026-06-11T10:00:00",
            },
            {
                "id": 44,
                "contact_name": "Tom Lin",
                "title": "Dismissed item",
                "status": "dismissed",
                "summary": "Do not show",
                "gmail_draft_id": None,
                "created_at": "2026-06-11T11:00:00",
            },
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.main(["list", "--contact", "Tom Lin"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls == [("/watchlist-alerts", "GET", None)]
    assert "Reviewable watchlist alerts for Tom Lin" in captured.out
    assert "alert #43" in captured.out
    assert "send --alert-id 43 --confirm '沒有問題'" in captured.out
    assert "alert #42" in captured.out
    assert "draft --alert-id 42" in captured.out
    assert "Dismissed item" not in captured.out
    assert "read-only; no Gmail was sent" in captured.out


def test_review_script_list_mode_can_filter_send_ready_alerts(monkeypatch, capsys):
    script = load_review_script_module()

    def fake_api_json(path, method="GET", payload=None):
        assert path == "/watchlist-alerts"
        assert method == "GET"
        return [
            {
                "id": 42,
                "contact_name": "Tom Lin",
                "title": "Needs Gmail draft",
                "status": "pending_review",
                "summary": "107 Brownstone Circle",
                "gmail_draft_id": None,
                "created_at": "2026-06-11T09:00:00",
            },
            {
                "id": 43,
                "contact_name": "Tom Lin",
                "title": "Ready draft",
                "status": "draft_created",
                "summary": "109 Brownstone Circle",
                "gmail_draft_id": "draft-123",
                "created_at": "2026-06-11T10:00:00",
            },
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.main(["list", "--action", "send"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "alert #43" in captured.out
    assert "send --alert-id 43 --confirm '沒有問題'" in captured.out
    assert "alert #42" not in captured.out
    assert "draft --alert-id 42" not in captured.out


def test_review_script_list_mode_reports_empty_safely(monkeypatch, capsys):
    script = load_review_script_module()
    monkeypatch.setattr(script, "api_json", lambda *_args, **_kwargs: [])

    exit_code = script.main(["list", "--contact", "Amy Yuen"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No reviewable watchlist alerts found" in captured.out
    assert "no Gmail was sent and no CRM data was changed" in captured.out


def test_review_script_blocks_send_when_gmail_draft_is_missing(monkeypatch, capsys):
    script = load_review_script_module()

    def fake_api_json(path, method="GET", payload=None):
        assert path == "/watchlist-alerts"
        assert method == "GET"
        return [
            {
                "id": 42,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin update",
                "status": "pending_review",
                "summary": "107 Brownstone Circle",
                "analysis": "Matches the seller watchlist.",
                "gmail_draft_id": None,
            }
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.send_reviewed_alert(42, confirmation="沒有問題", dry_run=True)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "does not have a Gmail draft yet" in captured.out


def test_review_script_dry_run_send_uses_review_gated_endpoint(monkeypatch, capsys):
    script = load_review_script_module()
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        assert path == "/watchlist-alerts"
        assert method == "GET"
        return [
            {
                "id": 42,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin update",
                "status": "draft_created",
                "summary": "107 Brownstone Circle",
                "analysis": "Matches the seller watchlist.",
                "gmail_draft_id": "draft-123",
            }
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.send_reviewed_alert(42, confirmation="OK", dry_run=True)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls == [("/watchlist-alerts", "GET", None)]
    assert "Dry run: would POST review-gated send request" in captured.out
    assert '"/watchlist-alerts/42/send"' in captured.out
    assert '"review_confirmation": "OK"' in captured.out


def test_review_script_send_posts_confirmation_when_not_dry_run(monkeypatch, capsys):
    script = load_review_script_module()
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if method == "GET":
            return [
                {
                    "id": 42,
                    "contact_id": 7,
                    "watchlist_id": 3,
                    "contact_name": "Tom Lin",
                    "title": "Tom Lin update",
                    "status": "draft_created",
                    "summary": "107 Brownstone Circle",
                    "analysis": "Matches the seller watchlist.",
                    "gmail_draft_id": "draft-123",
                }
            ]
        assert path == "/watchlist-alerts/42/send"
        assert payload == {"confirm_send": True, "review_confirmation": "沒有問題"}
        return {"success": True, "status": "sent", "gmail_message_id": "msg-123"}

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.send_reviewed_alert(42, confirmation="沒有問題", dry_run=False)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[-1] == (
        "/watchlist-alerts/42/send",
        "POST",
        {"confirm_send": True, "review_confirmation": "沒有問題"},
    )
    assert "Sent: Gmail reported the reviewed draft as sent." in captured.out


def test_review_script_send_can_resolve_unique_contact_draft(monkeypatch, capsys):
    script = load_review_script_module()

    def fake_api_json(path, method="GET", payload=None):
        assert path == "/watchlist-alerts"
        assert method == "GET"
        return [
            {
                "id": 42,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin digest item 1",
                "status": "draft_created",
                "summary": "107 Brownstone Circle",
                "analysis": "Matches the seller watchlist.",
                "gmail_draft_id": "draft-123",
                "interaction_id": 99,
                "created_at": "2026-06-11T09:00:00",
            },
            {
                "id": 43,
                "contact_id": 7,
                "watchlist_id": 3,
                "contact_name": "Tom Lin",
                "title": "Tom Lin digest item 2",
                "status": "draft_created",
                "summary": "109 Brownstone Circle",
                "analysis": "Part of the same digest.",
                "gmail_draft_id": "draft-123",
                "interaction_id": 99,
                "created_at": "2026-06-11T09:01:00",
            },
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.send_reviewed_alert(contact="Tom Lin", confirmation="OK", dry_run=True)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "alert #43" in captured.out
    assert '"/watchlist-alerts/43/send"' in captured.out
    assert "Dry run: would POST review-gated send request" in captured.out


def test_review_script_contact_send_blocks_multiple_distinct_drafts(monkeypatch, capsys):
    script = load_review_script_module()

    def fake_api_json(path, method="GET", payload=None):
        assert path == "/watchlist-alerts"
        return [
            {
                "id": 42,
                "contact_name": "Tom Lin",
                "title": "Tom Lin digest 1",
                "status": "draft_created",
                "gmail_draft_id": "draft-123",
                "interaction_id": 99,
                "created_at": "2026-06-11T09:00:00",
            },
            {
                "id": 44,
                "contact_name": "Tom Lin",
                "title": "Tom Lin digest 2",
                "status": "draft_created",
                "gmail_draft_id": "draft-456",
                "interaction_id": 100,
                "created_at": "2026-06-11T10:00:00",
            },
        ]

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.send_reviewed_alert(contact="Tom Lin", confirmation="沒有問題", dry_run=True)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "multiple send candidates" in captured.out
    assert "Use --alert-id" in captured.out
    assert "draft-123" in captured.out
    assert "draft-456" in captured.out


def test_review_script_contact_draft_resolves_existing_crm_draft(monkeypatch, capsys):
    script = load_review_script_module()
    calls = []

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if method == "GET":
            return [
                {
                    "id": 42,
                    "contact_id": 7,
                    "watchlist_id": 3,
                    "contact_name": "Tom Lin",
                    "title": "Tom Lin update",
                    "status": "draft_created",
                    "summary": "107 Brownstone Circle",
                    "analysis": "CRM draft exists but Gmail draft is missing.",
                    "gmail_draft_id": None,
                    "interaction_id": 99,
                    "created_at": "2026-06-11T09:00:00",
                }
            ]
        assert path == "/watchlist-alerts/42/gmail-draft"
        return {"success": True, "message": "Gmail draft created.", "to_email": "tom@example.com"}

    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.create_gmail_draft(contact="Tom Lin")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[-1] == ("/watchlist-alerts/42/gmail-draft", "POST", None)
    assert "Gmail draft action result" in captured.out


def test_resolve_watchlists_for_manual_check_contact_exact_returns_all_contact_watchlists():
    script = load_script_module()

    result = script.resolve_watchlists_for_manual_check(
        [
            {"id": 9, "contact_name": "Tom Lin", "name": "Tom seller sold comps"},
            {"id": 4, "contact_name": "Tom Lin", "name": "Tom seller active listings"},
            {"id": 2, "contact_name": "Amy Yuen", "name": "Amy buyer watch"},
        ],
        contact="Tom Lin",
    )

    assert [item["id"] for item in result] == [4, 9]


def test_resolve_watchlists_for_manual_check_blocks_ambiguous_contact():
    script = load_script_module()

    with pytest.raises(RuntimeError) as exc:
        script.resolve_watchlists_for_manual_check(
            [
                {"id": 1, "contact_name": "Tom Lin", "name": "Seller watch"},
                {"id": 2, "contact_name": "Tom Ling", "name": "Buyer watch"},
            ],
            contact="Tom",
        )

    assert "manual_check_contact_ambiguous:Tom" in str(exc.value)
    assert "#1 Tom Lin" in str(exc.value)
    assert "#2 Tom Ling" in str(exc.value)


def test_manual_check_by_contact_posts_selected_watchlist_without_sending(monkeypatch, capsys):
    script = load_script_module()
    calls = []

    def fail_import(*_args, **_kwargs):
        raise AssertionError("manual --skip-source-import should not import sources")

    def fake_api_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if "/send" in path:
            raise AssertionError("manual check must not send client emails")
        if path == "/property-feed/config":
            return {"gmail_feed_enabled": False}
        if path == "/watchlists":
            return [
                {
                    "id": 1,
                    "contact_name": "Tom Lin",
                    "name": "Tom seller active + sold",
                    "watch_type": "seller_listing_and_sold",
                },
                {
                    "id": 2,
                    "contact_name": "Amy Yuen",
                    "name": "Amy buyer watch",
                    "watch_type": "buyer_match",
                },
            ]
        if path == "/watchlists/1/check":
            assert method == "POST"
            return {
                "watchlist": {"id": 1, "contact_name": "Tom Lin", "name": "Tom seller active + sold"},
                "created_count": 1,
                "matched_properties": 2,
                "data_source_status": "internal",
                "message": "Created 1 alert.",
                "alerts": [
                    {
                        "id": 42,
                        "contact_name": "Tom Lin",
                        "title": "Tom Lin: Brownstone Circle comp",
                        "status": "draft_created",
                        "score": 86,
                        "gmail_draft_id": "draft-123",
                    }
                ],
            }
        if path == "/property-source/status":
            return {"internal_properties_ready": True, "properties_count": 8}
        raise AssertionError(f"unexpected API call: {method} {path}")

    monkeypatch.setattr(script, "ensure_backend_running", lambda: {"started": False, "status": "already_running"})
    monkeypatch.setattr(script, "import_csv_drop_folder", fail_import)
    monkeypatch.setattr(script, "import_gmail_saved_search_feeds", fail_import)
    monkeypatch.setattr(script, "api_json", fake_api_json)

    exit_code = script.main(["check", "--contact", "Tom Lin", "--skip-source-import"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert ("/watchlists/1/check", "POST", None) in calls
    assert all("/send" not in path for path, _method, _payload in calls)
    assert "SKC CRM 手動 Watchlist 檢查" in captured.out
    assert "Target：Tom Lin" in captured.out
    assert "new alerts=1" in captured.out
    assert "review_watchlist_alert.py send --alert-id 42 --confirm '沒有問題'" in captured.out
    assert "手動 check 不寄 Gmail、不 approve、不標記 sent" in captured.out


def test_summarize_source_task_includes_query_folder_and_next_step():
    script = load_script_module()

    summary = script.summarize_source_task(
        {
            "contact_name": "Amy Yuen",
            "priority": "source_required",
            "required_statuses": ["listed_for_sale"],
            "missing_required_statuses": ["listed_for_sale"],
            "client_email_needed": False,
            "saved_search_name": "SKC Amy Yuen - Buyer Active Listings",
            "gmail_query": "newer_than:14d Halton Hills detached",
            "drop_folder": "/tmp/watchlist-imports",
            "steps": ["Export rows for: listed for sale."],
        }
    )

    assert "Amy Yuen" in summary
    assert "priority=source required" in summary
    assert "listed for sale" in summary
    assert "saved_search=SKC Amy Yuen - Buyer Active Listings" in summary
    assert "query=newer_than:14d Halton Hills detached" in summary
    assert "drop_folder=/tmp/watchlist-imports" in summary
    assert "next=Export rows for: listed for sale." in summary


def test_summarize_launch_action_item_includes_saved_search_and_next_step():
    script = load_script_module()

    summary = script.summarize_launch_action_item(
        {
            "contact_name": "Tom Lin",
            "priority": "source_required",
            "source_ready": False,
            "delivery_ready": False,
            "client_email_needed": True,
            "missing_required_statuses": ["listed_for_sale", "sold"],
            "saved_search_name": "SKC Tom Lin - Seller Active + Sold Comps",
            "gmail_query": "newer_than:14d Thornhill townhouse",
            "actions": ["Add Tom Lin's client email."],
        }
    )

    assert "Tom Lin" in summary
    assert "priority=source required" in summary
    assert "email_needed=True" in summary
    assert "listed for sale, sold" in summary
    assert "saved_search=SKC Tom Lin - Seller Active + Sold Comps" in summary
    assert "query=newer_than:14d Thornhill townhouse" in summary
    assert "next=Add Tom Lin's client email." in summary


def test_summarize_launch_preflight_check_includes_status_detail_and_next_step():
    script = load_script_module()

    summary = script.summarize_launch_preflight_check(
        {
            "label": "Authorized Source Data",
            "status": "blocked",
            "detail": "0 source row(s); 4 active watchlists still need matching required statuses.",
            "next_step": "Import authorized REALM/TRREB CSV rows.",
        }
    )

    assert "Authorized Source Data" in summary
    assert "blocked" in summary
    assert "0 source row" in summary
    assert "next=Import authorized REALM/TRREB CSV rows." in summary


def test_select_watchlist_check_strategy_checks_all_after_new_source_rows():
    script = load_script_module()

    strategy = script.select_watchlist_check_strategy(
        {
            "imported": [
                {"result": {"created": 1, "updated": 0}},
            ],
        },
        {"imports": []},
    )

    assert strategy["endpoint"] == "/watchlists/check-all"
    assert strategy["mode"] == "check_all_after_import"


def test_select_watchlist_check_strategy_checks_all_after_reso_connector_rows():
    script = load_script_module()

    strategy = script.select_watchlist_check_strategy(
        {"imported": []},
        {"imports": []},
        {"result": {"created": 0, "updated": 2}},
    )

    assert strategy["endpoint"] == "/watchlists/check-all"
    assert strategy["mode"] == "check_all_after_import"


def test_select_watchlist_check_strategy_checks_due_when_no_source_rows_changed():
    script = load_script_module()

    strategy = script.select_watchlist_check_strategy(
        {
            "imported": [
                {"result": {"created": 0, "updated": 0, "skipped": 5}},
            ],
        },
        {
            "imports": [
                {"result": {"created": 0, "updated": 0, "skipped": 2}},
            ],
        },
    )

    assert strategy["endpoint"] == "/watchlists/check-due"
    assert strategy["mode"] == "check_due_only"


def test_summarize_delivery_gate_includes_safety_state():
    script = load_script_module()

    summary = script.summarize_delivery_gate(
        {
            "contact_name": "Tom Lin",
            "delivery_state": "auto_send_armed_draft_only",
            "review_mode": "auto_send_approved",
            "contact_email_present": True,
            "gmail_connected": True,
            "can_auto_send": False,
            "notification_ready": True,
            "action_required": "Server auto-send is off.",
        }
    )

    assert "Tom Lin" in summary
    assert "state=auto send armed draft only" in summary
    assert "mode=auto send approved" in summary
    assert "email=True" in summary
    assert "auto_send=False" in summary
    assert "next=Server auto-send is off." in summary


def test_readiness_report_helpers_include_blocking_status():
    script = load_script_module()
    check_result = {"checked": 2, "created_alerts": 0, "matched_properties": 0}
    source = {"properties_count": 0}
    csv_import = {"imported": []}
    readiness = {
        "overall_status": "blocked",
        "ready_count": 0,
        "active_count": 2,
        "blocked_count": 2,
    }

    message = script.build_run_message(check_result, source, csv_import, readiness)

    assert "readiness=blocked" in message
    assert "ready=0/2" in message
    assert "blocked=2" in message


def test_build_run_message_can_include_check_strategy():
    script = load_script_module()

    message = script.build_run_message(
        {"checked": 4, "created_alerts": 2, "matched_properties": 3},
        {"properties_count": 10},
        {"imported": [{"file": "/tmp/source.csv"}]},
        {"overall_status": "warning", "ready_count": 1, "active_count": 4, "blocked_count": 2},
        {"mode": "check_all_after_import"},
        reso_connector_import={"result": {"created": 1, "updated": 2}},
    )

    assert "strategy=check_all_after_import" in message
    assert "created_alerts=2" in message
    assert "reso_created=1" in message
    assert "reso_updated=2" in message


def test_codex_notification_summary_prioritizes_actionable_status():
    script = load_script_module()

    summary = script.build_codex_notification_summary(
        {
            "ok": True,
            "check_result": {
                "checked": 4,
                "created_alerts": 2,
                "next_watchlists": [
                    {
                        "contact_name": "Amy Yuen",
                        "schedule": {"times": ["09:00", "15:00"], "timezone": "America/Toronto"},
                        "next_check_at": "2026-06-11T13:00:00",
                    },
                    {
                        "contact_name": "Tom Lin",
                        "schedule": {"times": ["09:00"], "timezone": "America/Toronto"},
                        "next_check_at": "2026-06-11T13:00:00",
                    },
                ],
            },
            "property_source": {"properties_count": 6, "csv_drop_folder_pending_count": 1},
            "readiness_report": {
                "overall_status": "blocked",
                "next_actions": ["Import authorized REALM/TRREB rows."],
            },
            "launch_action_pack": {
                "missing_email_count": 3,
                "gmail_feed_enabled": False,
                "auto_send_server_enabled": False,
                "next_actions": ["Add Tom Lin's client email."],
            },
            "delivery_gates": {
                "ready_count": 1,
                "active_count": 4,
                "items": [
                    {"contact_name": "Tom Lin", "contact_email_present": False},
                    {"contact_name": "Cindy Chen", "contact_email_present": False},
                    {"contact_name": "David Wong", "contact_email_present": False},
                    {"contact_name": "Amy Yuen", "contact_email_present": True},
                ],
            },
            "source_tasks": {
                "tasks": [
                    {
                        "contact_name": "Amy Yuen",
                        "source_ready": False,
                        "missing_required_statuses": ["listed_for_sale"],
                    },
                    {
                        "contact_name": "Tom Lin",
                        "source_ready": False,
                        "missing_required_statuses": ["listed_for_sale", "sold"],
                    },
                    {
                        "contact_name": "Cindy Chen",
                        "source_ready": False,
                        "missing_required_statuses": ["listed_for_rent"],
                    },
                    {
                        "contact_name": "Kevin Chou",
                        "source_ready": True,
                        "missing_required_statuses": [],
                    },
                ],
            },
            "csv_drop_import": {"message": "CSV drop-folder processed 1 new file(s); skipped 0 already imported file(s)."},
            "gmail_feed_import": {"enabled": False},
            "helper_files": {
                "enabled": True,
                "drop_dir": "/tmp/watchlist-imports",
                "files": [
                    {"filename": "watchlist-next-actions.md"},
                    {"filename": "client-email-tasks.template.csv.disabled"},
                ],
            },
            "notification_logs": [
                {
                    "alert_id": 42,
                    "title": "Tom Lin: 2 watchlist update(s)",
                    "body": "\n".join(
                        [
                            "Property: 107 Brownstone Circle | Townhouse | $1,199,000",
                            "Why it matches: 比對分數 70，符合 Thornhill townhouse.",
                            "Draft: Gmail draft created and waiting for Kevin review.",
                            "Review in CRM: /watchlists?contact_id=7&alert_id=42&watchlist_id=3",
                        ]
                    ),
                }
            ],
        }
    )

    assert summary.startswith("SKC CRM Watchlist 通知")
    assert "new alerts=2" in summary
    assert "source rows=6" in summary
    assert "pending CSV=1" in summary
    assert "missing email(s)=3" in summary
    assert "Gmail feed=off" in summary
    assert "watchlist-next-actions.md" in summary
    assert "client-email-tasks.template.csv.disabled" in summary
    assert "/tmp/watchlist-imports" in summary
    assert "排程：下一次 Amy Yuen | 2026-06-11 09:00 America/Toronto +1 more" in summary
    assert "Email：需要補 Tom Lin, Cindy Chen, David Wong" in summary
    assert "client-email-tasks.csv" in summary
    assert "Source：需匯入 Amy Yuen(listed for sale), Tom Lin(listed for sale/sold), Cindy Chen(listed for rent)" in summary
    assert "Source Kit/REALM/TRREB CSV/RESO JSON" in summary
    assert "Codex 通知（手機可先審）" in summary
    assert "Tom Lin: 2 watchlist update(s)" in summary
    assert "Property: 107 Brownstone Circle" in summary
    assert "Review on Mac: http://127.0.0.1:5174/watchlists?contact_id=7&alert_id=42&watchlist_id=3" in summary
    assert "Add Tom Lin's client email." in summary
    assert "不直接寄 Gmail" in summary


def test_codex_notification_summary_reports_failures_without_send():
    script = load_script_module()

    summary = script.build_codex_notification_summary({"ok": False, "error": "backend unavailable"})

    assert "結果：失敗" in summary
    assert "backend unavailable" in summary
    assert "沒有寄 Gmail" in summary


def test_codex_notification_summary_explains_no_alert_reason_and_strategy():
    script = load_script_module()

    summary = script.build_codex_notification_summary(
        {
            "ok": True,
            "check_strategy": {
                "mode": "check_due_only",
                "endpoint": "/watchlists/check-due",
                "reason": "No new source rows were imported; only due watchlists need to run.",
            },
            "check_result": {
                "checked": 0,
                "created_alerts": 0,
                "matched_properties": 0,
                "active_count": 2,
                "due_count": 0,
                "not_due_count": 2,
                "next_watchlists": [
                    {
                        "contact_name": "Tom Lin",
                        "schedule": {"times": ["09:00"], "timezone": "America/Toronto"},
                        "next_check_at": "2026-06-11T13:00:00",
                    },
                ],
            },
            "property_source": {"properties_count": 4, "csv_drop_folder_pending_count": 0},
            "readiness_report": {"overall_status": "ready", "active_count": 2, "blocked_count": 0},
            "delivery_gates": {"ready_count": 2, "active_count": 2, "items": []},
            "launch_action_pack": {"missing_email_count": 0, "auto_send_server_enabled": False},
            "csv_drop_import": {"message": "CSV drop-folder has no pending importable files."},
            "gmail_feed_import": {"enabled": False},
            "source_tasks": {"tasks": []},
            "notification_logs": [],
        }
    )

    assert "Strategy：check_due_only | /watchlists/check-due" in summary
    assert "本次沒有到點的 watchlist" in summary
    assert "Tom Lin" in summary
    assert "不直接寄 Gmail" in summary


def test_summarize_readiness_report_item_names_next_step():
    script = load_script_module()

    summary = script.summarize_readiness_report_item(
        {
            "contact_name": "Tom Lin",
            "severity": "blocked",
            "matching_source_rows": 0,
            "required_statuses": ["active_listing", "sold_comp"],
            "next_steps": ["Import matching REALM/TRREB rows."],
        }
    )

    assert "Tom Lin" in summary
    assert "blocked" in summary
    assert "active listing, sold comp" in summary
    assert "Import matching REALM/TRREB rows." in summary


def test_summarize_readiness_report_item_includes_delivery_issue():
    script = load_script_module()

    summary = script.summarize_readiness_report_item(
        {
            "contact_name": "Tom Lin",
            "severity": "warning",
            "matching_source_rows": 3,
            "required_statuses": ["listed_for_sale", "sold"],
            "matching_status_counts": {"listed_for_sale": 2, "sold": 1},
            "delivery_ready": False,
            "delivery_issues": [
                "Contact email is missing; Gmail drafts cannot be addressed to the client."
            ],
            "next_steps": ["Add the client's email before relying on Auto Gmail Draft or Auto Send."],
        }
    )

    assert "Tom Lin" in summary
    assert "delivery=Contact email is missing" in summary
    assert "Add the client's email" in summary


def test_summarize_watchlist_readiness_includes_ready_delivery():
    script = load_script_module()

    summary = script.summarize_watchlist_readiness(
        {
            "contact_name": "Amy Yuen",
            "name": "Amy buyer watch",
            "notification_channel": "codex_app",
            "readiness": {
                "severity": "ready",
                "matching_source_rows": 4,
                "required_statuses": ["listed_for_sale"],
                "matching_status_counts": {"listed_for_sale": 4},
                "delivery_ready": True,
                "contact_email_present": True,
                "next_steps": [],
            },
        }
    )

    assert "Amy Yuen" in summary
    assert "delivery=ready" in summary


def test_summarize_data_intake_item_reports_source_and_delivery():
    script = load_script_module()

    summary = script.summarize_data_intake_item(
        {
            "contact_name": "Tom Lin",
            "readiness": "blocked",
            "source_ready": False,
            "delivery_ready": False,
            "current_matching_rows": 0,
            "required_statuses": ["listed_for_sale", "sold"],
            "missing_required_statuses": ["listed_for_sale", "sold"],
            "matching_status_counts": {"listed_for_sale": 0, "sold": 0},
            "primary_next_step": "Import authorized REALM/TRREB rows for: listed for sale, sold.",
        }
    )

    assert "Tom Lin" in summary
    assert "source=missing (listed for sale, sold)" in summary
    assert "delivery=client email needed" in summary
    assert "Import authorized REALM/TRREB rows" in summary


def test_format_schedule_line_displays_toronto_local_time():
    script = load_script_module()

    line = script.format_schedule_line(
        {
            "contact_name": "Amy Yuen",
            "schedule": {"times": ["09:00", "15:00"], "timezone": "America/Toronto"},
            "next_check_at": "2026-06-11T13:00:00",
            "last_checked_at": "2026-06-11T05:00:00",
            "notification_channel": "codex_app",
            "review_mode": "manual_review",
        }
    )

    assert "next=2026-06-11 09:00 America/Toronto" in line
    assert "last=2026-06-11 01:00 America/Toronto" in line
