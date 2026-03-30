import base64
import json
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app import models as crm_models
from app.agents import listing_alert_recommendation_gmail
from app.agents import models as agent_models
from app.agents import schemas as agent_schemas
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def encode_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


class ListingAlertRecommendationGmailImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.stage = crm_models.PipelineStage(name="Lead", order=1)
        self.db.add(self.stage)
        self.db.commit()
        self.db.refresh(self.stage)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_contact(self, **overrides):
        defaults = {
            "name": "Manual Mode Buyer",
            "email": "buyer@example.com",
            "client_type": "buyer",
            "status": "active",
            "stage_id": self.stage.id,
            "preferred_language": "en",
            "budget_min": 700000,
            "budget_max": 900000,
            "preferred_areas": json.dumps(["King West", "CityPlace"]),
            "property_preferences": json.dumps({"types": ["condo"]}),
            "created_at": utcnow_naive() - timedelta(days=10),
            "last_contacted_at": utcnow_naive() - timedelta(days=1),
        }
        defaults.update(overrides)
        contact = crm_models.Contact(**defaults)
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def create_interaction(self, contact_id: int):
        interaction = crm_models.Interaction(
            contact_id=contact_id,
            channel="email",
            direction="inbound",
            interaction_type="email",
            notes="Client wants a shortlist near transit.",
            date=utcnow_naive() - timedelta(hours=8),
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def gmail_config(self, **overrides):
        payload = {
            "access_token": "test-access-token",
            "gmail_user_id": "me",
            "query_policy": {
                "allowed_sender": "alerts@mls.example",
                "label_ids": ["mls-alerts"],
                "subject_keywords": ["Toronto MLS Alert"],
                "max_results": 5,
            },
        }
        payload.update(overrides)
        return agent_schemas.ListingAlertGmailReadConfig(**payload)

    def list_response(self, *, message_id: str, thread_id: str):
        return {"messages": [{"id": message_id, "threadId": thread_id}]}

    def gmail_message_response(
        self,
        *,
        message_id: str = "gmail-msg-1",
        thread_id: str = "gmail-thread-1",
        subject: str = "Toronto MLS Alert",
        from_address: str = "alerts@mls.example",
        to_addresses: str = "kevin@skc.example",
        cc_addresses: str = "assistant@skc.example",
        label_ids: list[str] | None = None,
        internal_date_ms: str = "1711800000000",
        plain_text_body: str | None = None,
        html_body: str | None = None,
        attachment_name: str | None = "listing.pdf",
    ):
        if plain_text_body is None:
            plain_text_body = (
                "Toronto MLS Saved Search Results\n\n"
                "123 King St W #1208\n"
                "MLS#: C1234567\n"
                "For Sale\n"
                "Price: $859,000\n"
                "Condo\n"
                "2 Bed | 2 Bath\n"
                "Area: King West\n"
                "https://example.com/listings/123-king\n"
            )
        if html_body is None:
            html_body = "<p>Toronto MLS Saved Search Results</p>"

        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": encode_body(plain_text_body)},
                "filename": "",
            },
            {
                "mimeType": "text/html",
                "body": {"data": encode_body(html_body)},
                "filename": "",
            },
        ]
        if attachment_name:
            parts.append(
                {
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att-1"},
                    "filename": attachment_name,
                }
            )

        return {
            "id": message_id,
            "threadId": thread_id,
            "labelIds": label_ids or ["mls-alerts"],
            "snippet": "Toronto MLS Saved Search Results",
            "internalDate": internal_date_ms,
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": subject},
                    {"name": "From", "value": from_address},
                    {"name": "To", "value": to_addresses},
                    {"name": "Cc", "value": cc_addresses},
                    {
                        "name": "Date",
                        "value": "Fri, 29 Mar 2026 13:30:00 -0400",
                    },
                ],
                "parts": parts,
            },
        }

    def audit_actions(self):
        logs = (
            self.db.query(agent_models.AgentAuditLog)
            .order_by(agent_models.AgentAuditLog.id.asc())
            .all()
        )
        return [log.action for log in logs]

    def test_fetch_and_import_gmail_alerts_feeds_existing_manual_packet_path(self):
        contact = self.create_contact()
        self.create_interaction(contact.id)

        with patch.object(
            listing_alert_recommendation_gmail,
            "_gmail_api_request_json",
            side_effect=[
                self.list_response(
                    message_id="gmail-msg-1",
                    thread_id="gmail-thread-1",
                ),
                self.gmail_message_response(),
            ],
        ):
            batch = listing_alert_recommendation_gmail.fetch_and_import_gmail_alerts(
                self.db,
                self.gmail_config(),
                expected_contact_id=contact.id,
                operator_notes="Imported via Gmail API.",
            )

        self.assertEqual(batch.matched_message_count, 1)
        self.assertEqual(batch.outcomes[0].status, "imported")
        self.assertEqual(batch.outcomes[0].message_id, "gmail-msg-1")
        self.assertEqual(batch.outcomes[0].thread_id, "gmail-thread-1")
        self.assertIsNotNone(batch.outcomes[0].normalized_message)
        self.assertEqual(
            batch.outcomes[0].normalized_message.attachment_names,
            ["listing.pdf"],
        )

        imported_run = (
            self.db.query(agent_models.AgentRun)
            .filter(agent_models.AgentRun.id == batch.outcomes[0].imported_run_id)
            .first()
        )
        self.assertIsNotNone(imported_run)
        self.assertEqual(imported_run.status, "completed")
        stored_result = json.loads(imported_run.result)
        self.assertEqual(stored_result["execution_status"], "packet_ready")

        imported_task = (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == batch.outcomes[0].imported_task_id)
            .first()
        )
        self.assertIsNotNone(imported_task)
        payload = json.loads(imported_task.payload)
        self.assertEqual(payload["gmail_alert"]["message_id"], "gmail-msg-1")
        self.assertEqual(
            payload["operator_notes"],
            "Imported via Gmail API.",
        )

        actions = self.audit_actions()
        self.assertIn("listing_alert_gmail_query_executed", actions)
        self.assertIn("listing_alert_gmail_message_fetched", actions)
        self.assertIn("listing_alert_gmail_message_imported", actions)
        self.assertIn("listing_alert_manual_packet_prepared", actions)

    def test_duplicate_message_id_returns_existing_run_reference(self):
        contact = self.create_contact()
        self.create_interaction(contact.id)
        config = self.gmail_config()

        with patch.object(
            listing_alert_recommendation_gmail,
            "_gmail_api_request_json",
            side_effect=[
                self.list_response(
                    message_id="gmail-msg-dup",
                    thread_id="gmail-thread-dup",
                ),
                self.gmail_message_response(
                    message_id="gmail-msg-dup",
                    thread_id="gmail-thread-dup",
                ),
            ],
        ):
            first_batch = listing_alert_recommendation_gmail.fetch_and_import_gmail_alerts(
                self.db,
                config,
                expected_contact_id=contact.id,
            )

        task_count = self.db.query(agent_models.AgentTask).count()
        run_count = self.db.query(agent_models.AgentRun).count()

        with patch.object(
            listing_alert_recommendation_gmail,
            "_gmail_api_request_json",
            side_effect=[
                self.list_response(
                    message_id="gmail-msg-dup",
                    thread_id="gmail-thread-dup",
                ),
            ],
        ):
            second_batch = listing_alert_recommendation_gmail.fetch_and_import_gmail_alerts(
                self.db,
                config,
                expected_contact_id=contact.id,
            )

        outcome = second_batch.outcomes[0]
        self.assertEqual(outcome.status, "duplicate_skipped")
        self.assertEqual(outcome.reason, "message_id_already_imported")
        self.assertEqual(
            outcome.existing_task_id,
            first_batch.outcomes[0].imported_task_id,
        )
        self.assertEqual(
            outcome.existing_run_id,
            first_batch.outcomes[0].imported_run_id,
        )
        self.assertEqual(self.db.query(agent_models.AgentTask).count(), task_count)
        self.assertEqual(self.db.query(agent_models.AgentRun).count(), run_count)
        self.assertIn(
            "listing_alert_gmail_message_duplicate_skipped",
            self.audit_actions(),
        )

    def test_policy_skip_is_returned_when_fetched_message_fails_allowlist(self):
        config = self.gmail_config()

        with patch.object(
            listing_alert_recommendation_gmail,
            "_gmail_api_request_json",
            side_effect=[
                self.list_response(
                    message_id="gmail-msg-skip",
                    thread_id="gmail-thread-skip",
                ),
                self.gmail_message_response(
                    message_id="gmail-msg-skip",
                    thread_id="gmail-thread-skip",
                    from_address="other-sender@example.com",
                ),
            ],
        ):
            batch = listing_alert_recommendation_gmail.fetch_and_import_gmail_alerts(
                self.db,
                config,
            )

        outcome = batch.outcomes[0]
        self.assertEqual(outcome.status, "policy_skipped")
        self.assertEqual(outcome.reason, "sender_not_allowlisted")
        self.assertEqual(self.db.query(agent_models.AgentTask).count(), 0)
        self.assertEqual(self.db.query(agent_models.AgentRun).count(), 0)
        self.assertIn("listing_alert_gmail_message_fetched", self.audit_actions())
        self.assertIn(
            "listing_alert_gmail_message_policy_skipped",
            self.audit_actions(),
        )

    def test_build_constrained_gmail_query_requires_guardrails(self):
        policy = agent_schemas.ListingAlertGmailReadQueryPolicy(
            allowed_sender="alerts@mls.example",
            label_ids=[],
            subject_keywords=[],
            max_results=5,
        )

        with self.assertRaises(ValueError) as error:
            listing_alert_recommendation_gmail.build_constrained_gmail_query(policy)

        self.assertEqual(str(error.exception), "gmail_query_policy_too_broad")

    def test_fetch_normalized_gmail_message_maps_headers_and_bodies(self):
        with patch.object(
            listing_alert_recommendation_gmail,
            "_gmail_api_request_json",
            return_value=self.gmail_message_response(
                message_id="gmail-msg-normalized",
                thread_id="gmail-thread-normalized",
                label_ids=["mls-alerts", "priority"],
                subject="Toronto MLS Alert Downtown",
                html_body="<p>HTML body</p>",
            ),
        ):
            message = listing_alert_recommendation_gmail.fetch_normalized_gmail_message(
                self.gmail_config(),
                agent_schemas.ListingAlertGmailMessageReference(
                    message_id="gmail-msg-normalized",
                    thread_id="gmail-thread-normalized",
                ),
            )

        self.assertEqual(message.message_id, "gmail-msg-normalized")
        self.assertEqual(message.thread_id, "gmail-thread-normalized")
        self.assertEqual(message.from_address, "alerts@mls.example")
        self.assertEqual(message.to_addresses, ["kevin@skc.example"])
        self.assertEqual(message.cc_addresses, ["assistant@skc.example"])
        self.assertEqual(message.label_ids, ["mls-alerts", "priority"])
        self.assertIn("Toronto MLS Saved Search Results", message.plain_text_body)
        self.assertEqual(message.html_body, "<p>HTML body</p>")
        self.assertEqual(message.attachment_names, ["listing.pdf"])


if __name__ == "__main__":
    unittest.main()
