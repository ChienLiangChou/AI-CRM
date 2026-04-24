import sys
import types
import unittest
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app import models as crm_models
from app.agents import daily_market_scan_watchlists
from app.agents import models as agent_models
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import market_scan_providers
from app.database import Base


class StubPublicProvider(market_scan_providers.BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "public_listing"
    display_name = "Stub Public Provider"
    authentication_required = False
    auth_state: agent_schemas.DailyMarketScanProviderAuthState = "not_required"
    availability: agent_schemas.DailyMarketScanProviderAvailability = "available"
    detail_level = "lower_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "low"
    fallback_capable = True
    notes = ("Stub provider for watchlist tests.",)

    def scan_client_matches(self, context):
        return self.build_scan_result(status="completed", source_used="stub_public")

    def scan_condo_competitors(self, context):
        return self.build_scan_result(
            status="completed",
            source_used="stub_public",
            findings=[
                agent_schemas.DailyMarketScanFinding(
                    address="20 Stewart St #1205",
                    source_used="stub_public",
                    why_relevant=["same-building inventory pulse"],
                )
            ],
        )

    def scan_area_competitors(self, context):
        return self.build_scan_result(
            status="completed",
            source_used="stub_public",
            findings=[
                agent_schemas.DailyMarketScanFinding(
                    address="88 King St W",
                    source_used="stub_public",
                    why_relevant=["nearby inventory watch"],
                )
            ],
        )


class StubAuthenticatedUnavailableProvider(market_scan_providers.BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "authenticated_mls_browser"
    display_name = "Stub Authenticated Browser"
    authentication_required = True
    auth_state: agent_schemas.DailyMarketScanProviderAuthState = "unauthenticated"
    availability: agent_schemas.DailyMarketScanProviderAvailability = "limited"
    detail_level = "high_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "high"
    fallback_capable = False
    notes = ("Stub auth provider for watchlist tests.",)

    def _result(self):
        return self.build_scan_result(
            status="unauthenticated",
            failure_metadata=[
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="auth_unavailable",
                    message="Stub auth provider unavailable.",
                    retryable=True,
                )
            ],
        )

    def scan_client_matches(self, context):
        return self._result()

    def scan_condo_competitors(self, context):
        return self._result()

    def scan_area_competitors(self, context):
        return self._result()


class DailyMarketScanWatchlistTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        TestingSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create_property(
        self,
        *,
        property_type: str = "condo",
        street: str = "20 Stewart St",
        unit: str | None = "706",
        postal_code: str | None = "M5V1B1",
        listing_url: str | None = "https://www.realtor.ca/real-estate/building-search",
    ):
        property_record = crm_models.Property(
            unit=unit,
            street=street,
            city="Toronto",
            postal_code=postal_code,
            property_type=property_type,
            status="listed_for_sale",
            listing_url=listing_url,
        )
        self.db.add(property_record)
        self.db.commit()
        self.db.refresh(property_record)
        return property_record

    def test_watchlist_crud_and_scheduler_status(self):
        property_record = self.create_property()

        created = daily_market_scan_watchlists.create_watchlist(
            self.db,
            {
                "name": "Stewart St competitor watch",
                "enabled": True,
                "schedule_interval_minutes": 60,
                "run_request": {
                    "scan_mode": "competitor_watch",
                    "source_preference": "public_only",
                    "property_ids": [property_record.id],
                },
                "operator_notes": ["same-building pulse"],
            },
        )

        self.assertEqual(created.name, "Stewart St competitor watch")
        self.assertEqual(created.run_request.run_mode, "scheduled_monitor")
        self.assertTrue(created.enabled)
        self.assertIsNotNone(created.next_run_at)
        self.assertEqual(created.operator_notes, ["same-building pulse"])

        listed = daily_market_scan_watchlists.list_watchlists(self.db)
        self.assertEqual([item.id for item in listed], [created.id])

        status = daily_market_scan_watchlists.get_scheduler_status(
            self.db,
            now=created.created_at,
        )
        self.assertEqual(status.enabled_watchlist_count, 1)
        self.assertEqual(status.due_watchlist_count, 1)

        updated = daily_market_scan_watchlists.update_watchlist(
            self.db,
            created.id,
            {
                "name": "Stewart St competitor watch paused",
                "enabled": False,
                "schedule_interval_minutes": 120,
                "run_request": {
                    "scan_mode": "competitor_watch",
                    "source_preference": "public_only",
                    "property_ids": [property_record.id],
                },
                "operator_notes": [],
            },
        )
        self.assertFalse(updated.enabled)
        self.assertIsNone(updated.next_run_at)

    def test_trigger_watchlist_run_now_persists_scoped_daily_market_scan_run(self):
        property_record = self.create_property()
        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": StubPublicProvider(),
        }
        watchlist = daily_market_scan_watchlists.create_watchlist(
            self.db,
            {
                "name": "Stewart St competitor watch",
                "enabled": True,
                "schedule_interval_minutes": 60,
                "run_request": {
                    "scan_mode": "competitor_watch",
                    "source_preference": "public_only",
                    "property_ids": [property_record.id],
                },
            },
        )

        run = daily_market_scan_watchlists.trigger_watchlist_run_now(
            self.db,
            watchlist.id,
            provider_registry=provider_registry,
        )

        refreshed_watchlist = (
            self.db.query(agent_models.DailyMarketScanWatchlist)
            .filter(agent_models.DailyMarketScanWatchlist.id == watchlist.id)
            .first()
        )
        self.assertIsNotNone(refreshed_watchlist)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.task.subject_type, "daily_market_scan_watchlist")
        self.assertEqual(run.task.subject_id, watchlist.id)
        self.assertEqual(refreshed_watchlist.last_run_id, run.id)
        self.assertEqual(refreshed_watchlist.last_run_status, "completed")

        actions = [
            log.action
            for log in self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run.id)
            .order_by(agent_models.AgentAuditLog.id.asc())
            .all()
        ]
        self.assertIn("daily_market_scan_watchlist_run_linked", actions)

    def test_run_due_watchlists_once_triggers_only_due_enabled_rows_and_updates_scheduler_state(self):
        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": StubPublicProvider(),
        }
        property_record = self.create_property()
        due_watchlist = daily_market_scan_watchlists.create_watchlist(
            self.db,
            {
                "name": "Due watchlist",
                "enabled": True,
                "schedule_interval_minutes": 30,
                "run_request": {
                    "scan_mode": "competitor_watch",
                    "source_preference": "public_only",
                    "property_ids": [property_record.id],
                },
            },
        )
        disabled_watchlist = daily_market_scan_watchlists.create_watchlist(
            self.db,
            {
                "name": "Disabled watchlist",
                "enabled": False,
                "schedule_interval_minutes": 30,
                "run_request": {
                    "scan_mode": "competitor_watch",
                    "source_preference": "public_only",
                    "property_ids": [property_record.id],
                },
            },
        )

        due_row = (
            self.db.query(agent_models.DailyMarketScanWatchlist)
            .filter(agent_models.DailyMarketScanWatchlist.id == due_watchlist.id)
            .first()
        )
        disabled_row = (
            self.db.query(agent_models.DailyMarketScanWatchlist)
            .filter(agent_models.DailyMarketScanWatchlist.id == disabled_watchlist.id)
            .first()
        )
        due_time = due_row.created_at + timedelta(minutes=1)
        due_row.next_run_at = due_time
        disabled_row.next_run_at = due_time
        self.db.commit()

        result = daily_market_scan_watchlists.run_due_watchlists_once(
            self.db,
            now=due_time,
            provider_registry=provider_registry,
        )

        self.assertEqual(result["due_count"], 1)
        self.assertEqual(result["triggered_count"], 1)
        self.assertEqual(result["triggered_watchlist_ids"], [due_watchlist.id])

        scheduler_status = daily_market_scan_watchlists.get_scheduler_status(
            self.db,
            now=due_time,
        )
        self.assertEqual(scheduler_status.last_status, "completed")
        self.assertEqual(scheduler_status.last_due_count, 1)
        self.assertEqual(scheduler_status.last_triggered_count, 1)

    def test_router_watchlist_endpoints_are_scoped_and_safe(self):
        created = agent_router.create_daily_market_scan_watchlist(
            agent_schemas.DailyMarketScanWatchlistUpsertRequest(
                name="Empty safe watchlist",
                enabled=True,
                schedule_interval_minutes=15,
                run_request=agent_schemas.DailyMarketScanRunRequest(),
            ),
            db=self.db,
        )

        listed = agent_router.list_daily_market_scan_watchlists(db=self.db)
        scheduler_status = agent_router.get_daily_market_scan_watchlist_scheduler_status(
            db=self.db
        )
        run = agent_router.trigger_daily_market_scan_watchlist_run_now(
            created.id,
            db=self.db,
        )

        self.assertEqual([item.id for item in listed], [created.id])
        self.assertEqual(scheduler_status.enabled_watchlist_count, 1)
        self.assertEqual(run.task.subject_type, "daily_market_scan_watchlist")
        self.assertEqual(run.task.subject_id, created.id)

        updated = agent_router.update_daily_market_scan_watchlist(
            created.id,
            agent_schemas.DailyMarketScanWatchlistUpsertRequest(
                name="Empty safe watchlist updated",
                enabled=False,
                schedule_interval_minutes=30,
                run_request=agent_schemas.DailyMarketScanRunRequest(),
            ),
            db=self.db,
        )
        self.assertFalse(updated.enabled)

        agent_router.delete_daily_market_scan_watchlist(created.id, db=self.db)
        self.assertEqual(agent_router.list_daily_market_scan_watchlists(db=self.db), [])


if __name__ == "__main__":
    unittest.main()
