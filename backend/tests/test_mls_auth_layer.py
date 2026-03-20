import json
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import models as agent_models
from app.agents import mls_auth
from app.agents import schemas as agent_schemas
from app.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MlsAuthLayerTests(unittest.TestCase):
    def test_initial_status_contract_is_internal_and_unavailable(self):
        now = utcnow_naive()
        status = mls_auth.build_initial_status(now=now)

        self.assertEqual(status.provider, "stratus_authenticated")
        self.assertEqual(status.state, "unauthenticated")
        self.assertFalse(status.available)
        self.assertTrue(status.internal_only)
        self.assertEqual(status.mode, "manual_simulated")
        self.assertEqual(status.last_checked_at, now)

    def test_start_auth_attempt_creates_auth_in_progress_with_non_secret_references(self):
        now = utcnow_naive()
        response = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        self.assertFalse(response.reused_existing_attempt)
        self.assertEqual(response.status.state, "auth_in_progress")
        self.assertFalse(response.status.available)
        self.assertEqual(response.status.active_attempt_reference, response.attempt.attempt_reference)
        self.assertEqual(response.status.session_reference, response.attempt.session_reference)
        self.assertTrue(response.status.session_reference.startswith("mls_auth_session_stratus_authenticated_"))
        self.assertTrue(response.attempt.attempt_reference.startswith("mls_auth_attempt_stratus_authenticated_"))
        self.assertNotIn("otp", response.status.session_reference.lower())

    def test_start_auth_attempt_reuses_existing_active_attempt(self):
        now = utcnow_naive()
        first = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        second = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            current_status=first.status,
            active_attempt=first.attempt,
            now=now + timedelta(seconds=30),
        )

        self.assertTrue(second.reused_existing_attempt)
        self.assertEqual(second.attempt.attempt_reference, first.attempt.attempt_reference)
        self.assertEqual(second.status.session_reference, first.status.session_reference)
        self.assertEqual(second.status.state, "auth_in_progress")

    def test_start_auth_attempt_reuses_existing_awaiting_otp_attempt(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        awaiting_status, awaiting_attempt = mls_auth.mark_otp_required(
            status=started.status,
            attempt=started.attempt,
            now=now + timedelta(seconds=10),
        )

        reused = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            current_status=awaiting_status,
            active_attempt=awaiting_attempt,
            now=now + timedelta(seconds=20),
        )

        self.assertTrue(reused.reused_existing_attempt)
        self.assertEqual(reused.status.state, "awaiting_otp")
        self.assertEqual(reused.attempt.attempt_reference, awaiting_attempt.attempt_reference)

    def test_mark_otp_required_sets_explicit_timeout(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        status, attempt = mls_auth.mark_otp_required(
            status=started.status,
            attempt=started.attempt,
            now=now + timedelta(seconds=15),
        )

        self.assertEqual(status.state, "awaiting_otp")
        self.assertEqual(attempt.state, "awaiting_otp")
        self.assertTrue(attempt.otp_required)
        self.assertEqual(status.otp_requested_at, now + timedelta(seconds=15))
        self.assertEqual(
            status.otp_timeout_at,
            now + timedelta(seconds=15, minutes=mls_auth.OTP_TIMEOUT_MINUTES),
        )

    def test_submit_otp_requires_matching_attempt_and_session_reference(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        awaiting_status, awaiting_attempt = mls_auth.mark_otp_required(
            status=started.status,
            attempt=started.attempt,
            now=now + timedelta(seconds=10),
        )

        with self.assertRaisesRegex(ValueError, "auth_attempt_mismatch"):
            mls_auth.submit_otp_for_attempt(
                request=agent_schemas.MlsAuthSubmitOtpRequest(
                    provider="stratus_authenticated",
                    attempt_reference="bad_attempt_ref",
                    session_reference=awaiting_status.session_reference or "",
                    otp_code="123456",
                ),
                status=awaiting_status,
                attempt=awaiting_attempt,
                now=now + timedelta(seconds=30),
            )

        with self.assertRaisesRegex(ValueError, "session_reference_mismatch"):
            mls_auth.submit_otp_for_attempt(
                request=agent_schemas.MlsAuthSubmitOtpRequest(
                    provider="stratus_authenticated",
                    attempt_reference=awaiting_attempt.attempt_reference,
                    session_reference="bad_session_ref",
                    otp_code="123456",
                ),
                status=awaiting_status,
                attempt=awaiting_attempt,
                now=now + timedelta(seconds=30),
            )

        accepted = mls_auth.submit_otp_for_attempt(
            request=agent_schemas.MlsAuthSubmitOtpRequest(
                provider="stratus_authenticated",
                attempt_reference=awaiting_attempt.attempt_reference,
                session_reference=awaiting_attempt.session_reference,
                otp_code="123456",
            ),
            status=awaiting_status,
            attempt=awaiting_attempt,
            now=now + timedelta(seconds=30),
        )

        self.assertTrue(accepted.otp_accepted)
        self.assertEqual(accepted.status.state, "auth_in_progress")
        self.assertEqual(accepted.attempt.state, "auth_in_progress")
        self.assertIsNotNone(accepted.attempt.otp_submitted_at)

    def test_submit_otp_after_timeout_marks_state_failed_with_otp_timeout(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        awaiting_status, awaiting_attempt = mls_auth.mark_otp_required(
            status=started.status,
            attempt=started.attempt,
            now=now + timedelta(seconds=10),
        )

        timed_out = mls_auth.submit_otp_for_attempt(
            request=agent_schemas.MlsAuthSubmitOtpRequest(
                provider="stratus_authenticated",
                attempt_reference=awaiting_attempt.attempt_reference,
                session_reference=awaiting_attempt.session_reference,
                otp_code="123456",
            ),
            status=awaiting_status,
            attempt=awaiting_attempt,
            now=(awaiting_status.otp_timeout_at or now) + timedelta(seconds=1),
        )

        self.assertFalse(timed_out.otp_accepted)
        self.assertEqual(timed_out.status.state, "failed")
        self.assertEqual(timed_out.status.failure_reason, "otp_timeout")
        self.assertEqual(timed_out.attempt.failure_reason, "otp_timeout")

    def test_mark_auth_available_completes_attempt_and_clears_active_reference(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        status, attempt = mls_auth.mark_auth_available(
            status=started.status,
            attempt=started.attempt,
            now=now + timedelta(minutes=1),
            expires_at=now + timedelta(hours=4),
        )

        self.assertEqual(status.state, "available")
        self.assertTrue(status.available)
        self.assertIsNone(status.active_attempt_reference)
        self.assertEqual(status.expires_at, now + timedelta(hours=4))
        self.assertEqual(attempt.state, "available")
        self.assertIsNotNone(attempt.finished_at)

    def test_history_contract_sorts_newest_attempt_first(self):
        now = utcnow_naive()
        first = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        second = mls_auth.start_auth_attempt(
            request=agent_schemas.MlsAuthStartRequest(),
            current_status=mls_auth.build_initial_status(now=now + timedelta(hours=1)),
            now=now + timedelta(hours=1),
        )

        history = mls_auth.build_history_response(
            current_status=second.status,
            attempts=[first.attempt, second.attempt],
        )

        self.assertEqual(history.attempts[0].attempt_reference, second.attempt.attempt_reference)
        self.assertEqual(history.attempts[1].attempt_reference, first.attempt.attempt_reference)


class MlsAuthPersistenceTests(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_persisted_start_creates_task_run_and_current_status_snapshot(self):
        now = utcnow_naive()
        response = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        task = self.db.query(agent_models.AgentTask).one()
        run = self.db.query(agent_models.AgentRun).one()
        audits = (
            self.db.query(agent_models.AgentAuditLog)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )

        self.assertEqual(task.agent_type, "mls_auth")
        self.assertEqual(task.subject_type, "stratus_authenticated")
        self.assertEqual(task.status, "executing")
        self.assertEqual(run.status, "executing")
        self.assertEqual(run.task_id, task.id)
        self.assertEqual(self.db.query(agent_models.AgentApproval).count(), 0)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].action, "mls_auth_attempt_started")

        task_payload = json.loads(task.payload)
        run_result = json.loads(run.result)
        self.assertEqual(
            task_payload["current_status"]["active_attempt_reference"],
            response.attempt.attempt_reference,
        )
        self.assertEqual(
            run_result["attempt"]["attempt_reference"],
            response.attempt.attempt_reference,
        )
        self.assertEqual(run_result["current_status"]["state"], "auth_in_progress")

    def test_persisted_start_reuses_active_attempt_without_parallel_run(self):
        now = utcnow_naive()
        first = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )

        second = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now + timedelta(seconds=20),
        )

        task = self.db.query(agent_models.AgentTask).one()
        runs = self.db.query(agent_models.AgentRun).all()
        audits = (
            self.db.query(agent_models.AgentAuditLog)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )

        self.assertTrue(second.reused_existing_attempt)
        self.assertEqual(len(runs), 1)
        self.assertEqual(task.status, "executing")
        self.assertEqual(
            second.attempt.attempt_reference,
            first.attempt.attempt_reference,
        )
        self.assertEqual(audits[-1].action, "mls_auth_attempt_reused")

    def test_persisted_submit_otp_preserves_binding_and_never_persists_otp_value(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        awaiting_status, awaiting_attempt = mls_auth.mark_otp_required_persisted(
            self.db,
            provider="stratus_authenticated",
            attempt_reference=started.attempt.attempt_reference,
            now=now + timedelta(seconds=10),
        )

        response = mls_auth.submit_otp_for_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthSubmitOtpRequest(
                provider="stratus_authenticated",
                attempt_reference=awaiting_attempt.attempt_reference,
                session_reference=awaiting_attempt.session_reference,
                otp_code="654321",
            ),
            now=now + timedelta(seconds=20),
        )

        task = self.db.query(agent_models.AgentTask).one()
        run = self.db.query(agent_models.AgentRun).one()
        audit_logs = self.db.query(agent_models.AgentAuditLog).all()

        self.assertEqual(awaiting_status.state, "awaiting_otp")
        self.assertTrue(response.otp_accepted)
        self.assertEqual(task.status, "executing")
        self.assertEqual(json.loads(task.payload)["current_status"]["state"], "auth_in_progress")
        self.assertEqual(json.loads(run.result)["attempt"]["state"], "auth_in_progress")

        persisted_text = " ".join(
            filter(
                None,
                [
                    task.payload,
                    run.plan,
                    run.result,
                    *[audit.details or "" for audit in audit_logs],
                ],
            )
        )
        self.assertNotIn("654321", persisted_text)

    def test_otp_timeout_is_persisted_as_failed_with_audit_log(self):
        now = utcnow_naive()
        started = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        awaiting_status, awaiting_attempt = mls_auth.mark_otp_required_persisted(
            self.db,
            provider="stratus_authenticated",
            attempt_reference=started.attempt.attempt_reference,
            now=now + timedelta(seconds=5),
        )

        status = mls_auth.load_persisted_status(
            self.db,
            provider="stratus_authenticated",
            now=(awaiting_status.otp_timeout_at or now) + timedelta(seconds=1),
        )

        task = self.db.query(agent_models.AgentTask).one()
        run = self.db.query(agent_models.AgentRun).one()
        audits = (
            self.db.query(agent_models.AgentAuditLog)
            .order_by(agent_models.AgentAuditLog.created_at.asc())
            .all()
        )

        self.assertEqual(status.state, "failed")
        self.assertEqual(status.failure_reason, "otp_timeout")
        self.assertEqual(task.status, "failed")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "otp_timeout")
        self.assertEqual(json.loads(run.result)["attempt"]["failure_reason"], "otp_timeout")
        self.assertEqual(audits[-1].action, "mls_auth_otp_timed_out")

    def test_persisted_history_returns_newest_attempt_first(self):
        now = utcnow_naive()
        first = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now,
        )
        mls_auth.mark_auth_failed_persisted(
            self.db,
            provider="stratus_authenticated",
            attempt_reference=first.attempt.attempt_reference,
            failure_reason="provider_unavailable",
            now=now + timedelta(minutes=1),
        )

        second = mls_auth.start_auth_attempt_persisted(
            self.db,
            request=agent_schemas.MlsAuthStartRequest(),
            now=now + timedelta(minutes=2),
        )

        history = mls_auth.load_persisted_history(
            self.db,
            provider="stratus_authenticated",
            now=now + timedelta(minutes=2, seconds=5),
        )

        self.assertEqual(len(history.attempts), 2)
        self.assertEqual(
            history.attempts[0].attempt_reference,
            second.attempt.attempt_reference,
        )
        self.assertEqual(
            history.attempts[1].attempt_reference,
            first.attempt.attempt_reference,
        )
        self.assertEqual(history.current_status.active_attempt_reference, second.attempt.attempt_reference)


if __name__ == "__main__":
    unittest.main()
