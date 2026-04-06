import json
import os
import sys
import types
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app.agents import gmail_oauth
from app.agents import models as agent_models
from app.database import Base, get_db
from app.main import app


class ListingAlertRecommendationGmailOAuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.client = TestClient(app)

        self.original_env = {
            "GMAIL_OAUTH_CLIENT_ID": os.environ.get("GMAIL_OAUTH_CLIENT_ID"),
            "GMAIL_OAUTH_CLIENT_SECRET": os.environ.get("GMAIL_OAUTH_CLIENT_SECRET"),
            "GMAIL_OAUTH_REDIRECT_URI": os.environ.get("GMAIL_OAUTH_REDIRECT_URI"),
            "GMAIL_OAUTH_ENCRYPTION_KEY": os.environ.get("GMAIL_OAUTH_ENCRYPTION_KEY"),
        }
        os.environ["GMAIL_OAUTH_CLIENT_ID"] = "gmail-client-id"
        os.environ["GMAIL_OAUTH_CLIENT_SECRET"] = "gmail-client-secret"
        os.environ["GMAIL_OAUTH_REDIRECT_URI"] = (
            "http://localhost:8000/api/agents/"
            "listing-alert-recommendation/gmail/oauth/callback"
        )
        os.environ["GMAIL_OAUTH_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.db.close()
        self.engine.dispose()

    def _latest_state_record(self):
        return (
            self.db.query(agent_models.ListingAlertGmailOAuthState)
            .order_by(agent_models.ListingAlertGmailOAuthState.id.desc())
            .first()
        )

    def _connection(self):
        return (
            self.db.query(agent_models.ListingAlertGmailOAuthConnection)
            .filter(
                agent_models.ListingAlertGmailOAuthConnection.connection_key
                == gmail_oauth.LISTING_ALERT_GMAIL_CONNECTION_KEY
            )
            .first()
        )

    def assert_secret_not_persisted(self, secret: str):
        connection = self._connection()
        if connection is not None:
            self.assertNotIn(secret, connection.granted_scopes or "")
            self.assertNotIn(secret, connection.account_email or "")
            self.assertNotIn(secret, connection.last_error or "")

        task_payloads = [
            task.payload or ""
            for task in self.db.query(agent_models.AgentTask).all()
        ]
        run_payloads = []
        for run in self.db.query(agent_models.AgentRun).all():
            run_payloads.extend([run.plan or "", run.result or "", run.error or ""])
        audit_payloads = [
            log.details or ""
            for log in self.db.query(agent_models.AgentAuditLog).all()
        ]
        state_values = [
            state.state_hash or ""
            for state in self.db.query(agent_models.ListingAlertGmailOAuthState).all()
        ]

        for payload in task_payloads + run_payloads + audit_payloads + state_values:
            self.assertNotIn(secret, payload)

    def test_start_route_returns_authorization_url_and_hashed_state(self):
        response = self.client.post(
            "/api/agents/listing-alert-recommendation/gmail/oauth/start"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["connection_key"], "listing_alert_primary")
        self.assertEqual(
            payload["requested_scopes"],
            [gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE],
        )

        parsed = urlparse(payload["authorization_url"])
        params = parse_qs(parsed.query)
        self.assertEqual(params["client_id"], ["gmail-client-id"])
        self.assertEqual(params["redirect_uri"], [os.environ["GMAIL_OAUTH_REDIRECT_URI"]])
        self.assertEqual(params["scope"], [gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE])
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["prompt"], ["consent"])

        raw_state = params["state"][0]
        state_record = self._latest_state_record()
        self.assertIsNotNone(state_record)
        self.assertNotEqual(state_record.state_hash, raw_state)
        self.assertEqual(
            state_record.connection_key,
            gmail_oauth.LISTING_ALERT_GMAIL_CONNECTION_KEY,
        )

    def test_callback_route_stores_encrypted_refresh_token_and_returns_status(self):
        start_response = self.client.post(
            "/api/agents/listing-alert-recommendation/gmail/oauth/start"
        )
        raw_state = parse_qs(
            urlparse(start_response.json()["authorization_url"]).query
        )["state"][0]

        access_token = "oauth-access-token"
        refresh_token = "oauth-refresh-token"
        auth_code = "oauth-auth-code"

        with patch.object(
            gmail_oauth,
            "_exchange_code_for_tokens",
            return_value={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "scope": gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE,
                "expires_in": 3600,
            },
        ), patch.object(
            gmail_oauth,
            "_fetch_gmail_profile",
            return_value={"emailAddress": "listing.alerts@example.com"},
        ):
            response = self.client.get(
                "/api/agents/listing-alert-recommendation/gmail/oauth/callback",
                params={"state": raw_state, "code": auth_code},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "connected")
        self.assertEqual(payload["account_email"], "listing.alerts@example.com")
        self.assertTrue(payload["has_refresh_token"])
        self.assertFalse(payload["reconnect_required"])
        self.assertNotIn(access_token, response.text)
        self.assertNotIn(refresh_token, response.text)
        self.assertNotIn(auth_code, response.text)

        connection = self._connection()
        self.assertIsNotNone(connection)
        self.assertEqual(connection.status, "connected")
        self.assertEqual(connection.gmail_user_id, "me")
        self.assertEqual(connection.account_email, "listing.alerts@example.com")
        self.assertIsNotNone(connection.encrypted_refresh_token)
        self.assertNotEqual(connection.encrypted_refresh_token, refresh_token)

        state_record = self._latest_state_record()
        self.assertIsNotNone(state_record.used_at)
        self.assert_secret_not_persisted(access_token)
        self.assert_secret_not_persisted(refresh_token)
        self.assert_secret_not_persisted(auth_code)

    def test_callback_state_is_one_time_use(self):
        start_response = self.client.post(
            "/api/agents/listing-alert-recommendation/gmail/oauth/start"
        )
        raw_state = parse_qs(
            urlparse(start_response.json()["authorization_url"]).query
        )["state"][0]

        with patch.object(
            gmail_oauth,
            "_exchange_code_for_tokens",
            return_value={
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE,
            },
        ), patch.object(
            gmail_oauth,
            "_fetch_gmail_profile",
            return_value={"emailAddress": "listing.alerts@example.com"},
        ):
            first_response = self.client.get(
                "/api/agents/listing-alert-recommendation/gmail/oauth/callback",
                params={"state": raw_state, "code": "oauth-auth-code"},
            )
            second_response = self.client.get(
                "/api/agents/listing-alert-recommendation/gmail/oauth/callback",
                params={"state": raw_state, "code": "oauth-auth-code"},
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(
            second_response.json()["detail"],
            "Invalid Gmail OAuth callback",
        )

    def test_status_and_disconnect_routes_hide_tokens_and_clear_connection(self):
        connection = agent_models.ListingAlertGmailOAuthConnection(
            connection_key=gmail_oauth.LISTING_ALERT_GMAIL_CONNECTION_KEY,
            gmail_user_id="me",
            status="connected",
            account_email="listing.alerts@example.com",
            granted_scopes=json.dumps([gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE]),
            encrypted_refresh_token="encrypted-token",
        )
        self.db.add(connection)
        self.db.commit()

        status_response = self.client.get(
            "/api/agents/listing-alert-recommendation/gmail/oauth/status"
        )
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()
        self.assertEqual(status_payload["status"], "connected")
        self.assertTrue(status_payload["has_refresh_token"])
        self.assertNotIn("refresh_token", status_payload)
        self.assertNotIn("access_token", status_payload)

        disconnect_response = self.client.post(
            "/api/agents/listing-alert-recommendation/gmail/oauth/disconnect"
        )
        self.assertEqual(disconnect_response.status_code, 200)
        disconnect_payload = disconnect_response.json()
        self.assertEqual(disconnect_payload["status"], "disconnected")
        self.assertFalse(disconnect_payload["has_refresh_token"])

        refreshed_connection = self._connection()
        self.assertIsNotNone(refreshed_connection)
        self.assertIsNone(refreshed_connection.encrypted_refresh_token)
        self.assertIsNone(refreshed_connection.account_email)

    def test_refresh_helper_marks_reconnect_required_on_invalid_grant(self):
        config = gmail_oauth._load_oauth_config()
        connection = agent_models.ListingAlertGmailOAuthConnection(
            connection_key=gmail_oauth.LISTING_ALERT_GMAIL_CONNECTION_KEY,
            gmail_user_id="me",
            status="connected",
            account_email="listing.alerts@example.com",
            granted_scopes=json.dumps([gmail_oauth.LISTING_ALERT_GMAIL_READ_SCOPE]),
            encrypted_refresh_token=gmail_oauth._encrypt_refresh_token(
                config,
                "oauth-refresh-token",
            ),
        )
        self.db.add(connection)
        self.db.commit()

        with patch.object(
            gmail_oauth,
            "_refresh_access_token",
            side_effect=ValueError("gmail_oauth_refresh_token_invalid"),
        ):
            with self.assertRaises(ValueError) as error:
                gmail_oauth.refresh_listing_alert_gmail_access_token(self.db)

        self.assertEqual(str(error.exception), "gmail_oauth_refresh_token_invalid")
        refreshed_connection = self._connection()
        self.assertEqual(refreshed_connection.status, "reconnect_required")
        self.assertIsNone(refreshed_connection.encrypted_refresh_token)
        self.assertEqual(refreshed_connection.last_error, "invalid_grant")
