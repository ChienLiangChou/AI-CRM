import json
import sys
import types
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pywebpush_stub = types.ModuleType("pywebpush")
pywebpush_stub.webpush = lambda *args, **kwargs: None
pywebpush_stub.WebPushException = Exception
sys.modules.setdefault("pywebpush", pywebpush_stub)

from app import models as crm_models
from app.agents import models as agent_models
from app.agents import daily_market_scan
from app.agents import market_scan_providers
from app.agents import public_listing_fetcher, public_listing_normalizer
from app.agents import router as agent_router
from app.agents import schemas as agent_schemas
from app.agents import service as agent_service
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
    notes = ("Stub provider for tests.",)

    def scan_client_matches(self, context):
        return self.build_scan_result(
            status="completed",
            source_used="stub_public",
            fallback_used=True,
            findings=[
                agent_schemas.DailyMarketScanFinding(
                    address="20 Stewart St #706",
                    mls_number="C1234567",
                    source_used="stub_public",
                    why_it_matches=["budget fit"],
                    tradeoffs=["smaller den"],
                )
            ],
            failure_metadata=[
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="authenticated_source_unavailable",
                    message="Primary source unavailable; fallback used.",
                    retryable=True,
                    fallback_attempted=True,
                    fallback_used=True,
                )
            ],
            notes=["Stub fallback result."],
        )

    def scan_condo_competitors(self, context):
        return self.build_scan_result(
            status="completed",
            source_used="stub_public",
            fallback_used=True,
            findings=[
                agent_schemas.DailyMarketScanFinding(
                    address="20 Stewart St #706",
                    mls_number="C1234568",
                    source_used="stub_public",
                    why_relevant=["same-building inventory pulse"],
                    competitor_notes=["Comparable condo listing."],
                )
            ],
            notes=["Stub condo competitor result."],
        )

    def scan_area_competitors(self, context):
        return self.build_scan_result(
            status="completed",
            source_used="stub_public",
            fallback_used=True,
            findings=[
                agent_schemas.DailyMarketScanFinding(
                    address="88 King St W",
                    mls_number="W7654321",
                    source_used="stub_public",
                    why_relevant=["nearby inventory watch"],
                    competitor_notes=["Area-level competitor listing."],
                )
            ],
            notes=["Stub area competitor result."],
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
    notes = ("Stub authenticated provider for tests.",)

    def _result(self):
        return self.build_scan_result(
            status="unauthenticated",
            failure_metadata=[
                agent_schemas.DailyMarketScanFailureMetadata(
                    provider_key=self.provider_key,
                    code="auth_unavailable",
                    message="Stub auth provider unavailable.",
                    retryable=True,
                    fallback_attempted=False,
                    fallback_used=False,
                )
            ],
            notes=["Stub auth unavailable."],
        )

    def scan_client_matches(self, context):
        return self._result()

    def scan_condo_competitors(self, context):
        return self._result()

    def scan_area_competitors(self, context):
        return self._result()


class StubFailingAuthenticatedProvider(market_scan_providers.BaseMarketScanProvider):
    provider_key: agent_schemas.DailyMarketScanProviderKey = "authenticated_mls_browser"
    display_name = "Failing Authenticated Browser"
    authentication_required = True
    auth_state: agent_schemas.DailyMarketScanProviderAuthState = "authenticated"
    availability: agent_schemas.DailyMarketScanProviderAvailability = "available"
    detail_level = "high_detail"
    confidence_level: agent_schemas.DailyMarketScanProviderConfidence = "high"
    fallback_capable = False
    notes = ("Failing provider for tests.",)

    def scan_client_matches(self, context):
        raise RuntimeError("simulated_provider_failure")

    def scan_condo_competitors(self, context):
        raise RuntimeError("simulated_provider_failure")

    def scan_area_competitors(self, context):
        raise RuntimeError("simulated_provider_failure")


PUBLIC_LISTING_SEARCH_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
          {
            "@type": "ListItem",
            "position": 1,
            "item": {
              "@type": "Apartment",
              "name": "20 Stewart St #706, Toronto",
              "url": "https://www.realtor.ca/real-estate/1",
              "identifier": "C1234567",
              "address": {
                "@type": "PostalAddress",
                "streetAddress": "706 20 Stewart St",
                "addressLocality": "Toronto",
                "postalCode": "M5V1B1"
              },
              "offers": {
                "@type": "Offer",
                "price": "799000",
                "availability": "https://schema.org/InStock"
              }
            }
          },
          {
            "@type": "ListItem",
            "position": 2,
            "item": {
              "@type": "Apartment",
              "name": "20 Stewart St #1205, Toronto",
              "url": "https://www.realtor.ca/real-estate/2",
              "identifier": "C7654321",
              "address": {
                "@type": "PostalAddress",
                "streetAddress": "1205 20 Stewart St",
                "addressLocality": "Toronto",
                "postalCode": "M5V1B2"
              },
              "offers": {
                "@type": "Offer",
                "price": "845000",
                "availability": "https://schema.org/InStock"
              }
            }
          },
          {
            "@type": "ListItem",
            "position": 3,
            "item": {
              "@type": "SingleFamilyResidence",
              "name": "88 King St W, Toronto",
              "url": "https://www.realtor.ca/real-estate/3",
              "identifier": "W1112223",
              "address": {
                "@type": "PostalAddress",
                "streetAddress": "88 King St W",
                "addressLocality": "Toronto",
                "postalCode": "M5H1A1"
              },
              "offers": {
                "@type": "Offer",
                "price": "1399000",
                "availability": "https://schema.org/InStock"
              }
            }
          }
        ]
      }
    </script>
  </head>
</html>
"""

PUBLIC_LISTING_AREA_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
          {
            "@type": "ListItem",
            "position": 1,
            "item": {
              "@type": "SingleFamilyResidence",
              "name": "90 King St W, Toronto",
              "url": "https://www.realtor.ca/real-estate/4",
              "identifier": "W9000001",
              "address": {
                "@type": "PostalAddress",
                "streetAddress": "90 King St W",
                "addressLocality": "Toronto",
                "postalCode": "M5H1B1"
              },
              "offers": {
                "@type": "Offer",
                "price": "1499000",
                "availability": "https://schema.org/InStock"
              }
            }
          },
          {
            "@type": "ListItem",
            "position": 2,
            "item": {
              "@type": "SingleFamilyResidence",
              "name": "14 Elm St, Toronto",
              "url": "https://www.realtor.ca/real-estate/5",
              "identifier": "W9000002",
              "address": {
                "@type": "PostalAddress",
                "streetAddress": "14 Elm St",
                "addressLocality": "Toronto",
                "postalCode": "M4B1A1"
              },
              "offers": {
                "@type": "Offer",
                "price": "1299000",
                "availability": "https://schema.org/InStock"
              }
            }
          }
        ]
      }
    </script>
  </head>
</html>
"""

PUBLIC_LISTING_EMPTY_HTML = """
<html>
  <head><title>Empty public page</title></head>
  <body><div>No structured listing data here.</div></body>
</html>
"""


def build_public_page(url: str, html: str):
    return public_listing_fetcher.PublicListingFetchedPage(
        url=url,
        host="www.realtor.ca",
        html=html,
        status_code=200,
        content_type="text/html",
    )


def fake_realtor_fetch(url: str):
    if "area-search" in url:
        return build_public_page(url, PUBLIC_LISTING_AREA_HTML)
    return build_public_page(url, PUBLIC_LISTING_SEARCH_HTML)


def fake_empty_realtor_fetch(url: str):
    return build_public_page(url, PUBLIC_LISTING_EMPTY_HTML)


class DailyMarketScanContractTests(unittest.TestCase):
    def test_normalize_run_request_dedupes_and_clamps_scope(self):
        request = daily_market_scan.normalize_run_request(
            {
                "scan_mode": "full_daily_scan",
                "run_mode": "manual_preview",
                "source_preference": "auto",
                "contact_ids": [42, "51", None, "bad", -1, 42],
                "property_ids": [17, "18", 0, False, "bad", 17],
                "listing_refs": [
                    {
                        "listing_ref": "manual:downtown-condo",
                        "property_id": "17",
                        "label": "20 Stewart St #706",
                    },
                    {
                        "property_id": "19",
                        "label": "Auto-derived listing ref",
                    },
                    {"listing_ref": "", "property_id": None},
                    "bad",
                ],
                "max_subjects": 999,
            }
        )

        self.assertEqual(request.contact_ids, [42, 51])
        self.assertEqual(request.property_ids, [17, 18])
        self.assertEqual(len(request.listing_refs), 2)
        self.assertEqual(request.listing_refs[0].listing_ref, "manual:downtown-condo")
        self.assertEqual(request.listing_refs[1].listing_ref, "manual:property:19")
        self.assertEqual(request.max_subjects, daily_market_scan.MAX_MARKET_SCAN_SUBJECTS)

    def test_scope_summary_constrains_broad_v1_request(self):
        request = agent_schemas.DailyMarketScanRunRequest(
            scan_mode="full_daily_scan",
            run_mode="manual_preview",
            source_preference="auto",
            contact_ids=list(range(1, 21)),
            property_ids=list(range(21, 36)),
            listing_refs=[],
            max_subjects=25,
        )

        scope = daily_market_scan.build_scope_summary(request)

        self.assertEqual(scope.requested_subject_count, 35)
        self.assertEqual(scope.effective_subject_count, 25)
        self.assertEqual(scope.decision, "constrained")
        self.assertTrue(scope.notes)

    def test_provider_catalog_models_authenticated_primary_and_public_fallback(self):
        catalog = daily_market_scan.build_provider_catalog(
            {
                "scan_mode": "full_daily_scan",
                "run_mode": "manual_preview",
                "source_preference": "auto",
                "contact_ids": [42],
            },
            authenticated_mls_browser_auth_state="expired",
            authenticated_mls_browser_availability="limited",
            public_availability="available",
        )

        self.assertEqual(
            [item.provider_key for item in catalog],
            ["authenticated_mls_browser", "public_listing"],
        )
        self.assertEqual(catalog[0].auth_state, "expired")
        self.assertTrue(catalog[0].authentication_required)
        self.assertFalse(catalog[0].fallback_capable)
        self.assertEqual(catalog[1].auth_state, "not_required")
        self.assertTrue(catalog[1].fallback_capable)
        self.assertEqual(catalog[1].confidence_level, "low")

    def test_result_contract_is_internal_only_and_records_scope_failure_metadata(self):
        result = daily_market_scan.build_scan_result_contract(
            {
                "scan_mode": "full_daily_scan",
                "run_mode": "simulated_preview",
                "source_preference": "authenticated_mls_browser_first",
                "contact_ids": list(range(1, 40)),
            },
            authenticated_mls_browser_auth_state="unauthenticated",
            authenticated_mls_browser_availability="limited",
            public_availability="available",
        )

        self.assertEqual(result.execution_policy.mode, "internal_logging_review_only")
        self.assertFalse(result.execution_policy.can_auto_send)
        self.assertFalse(result.execution_policy.can_auto_contact_clients)
        self.assertFalse(result.execution_policy.can_create_client_outputs_without_approval)
        self.assertIn(
            "Daily market scan findings remain internal logging only until explicitly approved for external use.",
            result.operator_notes,
        )
        self.assertIn(
            "This layer is manual or simulated only in v1. It does not auto-send, auto-contact, or autonomously publish outputs.",
            result.operator_notes,
        )
        self.assertIn(daily_market_scan.SCOPE_CONSTRAINED_RISK_FLAG, result.risk_flags)
        self.assertEqual(result.failure_metadata[0].code, "scan_scope_exceeds_v1_limit")

    def test_stub_provider_is_mockable_and_returns_source_fallback_metadata(self):
        provider = StubPublicProvider()

        scan_result = provider.scan_client_matches({"contact_id": 42})
        source_attempt = provider.build_source_attempt(
            status="completed",
            source_used="stub_public",
            fallback_used=True,
            failure_metadata=scan_result.failure_metadata,
            notes=["Stub attempt."],
        )

        self.assertEqual(scan_result.provider_key, "public_listing")
        self.assertEqual(scan_result.findings[0].source_used, "stub_public")
        self.assertTrue(scan_result.fallback_used)
        self.assertEqual(
            scan_result.failure_metadata[0].code, "authenticated_source_unavailable"
        )
        self.assertEqual(source_attempt.source_used, "stub_public")
        self.assertTrue(source_attempt.fallback_used)
        self.assertEqual(
            source_attempt.failure_metadata[0].provider_key, "public_listing"
        )

    def test_public_only_preference_excludes_authenticated_browser_provider(self):
        result = daily_market_scan.build_scan_result_contract(
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "public_only",
                "contact_ids": [42],
            }
        )

        self.assertEqual(result.scan_summary.provider_order, ["public_listing"])
        self.assertEqual(
            [item.provider_key for item in result.provider_catalog], ["public_listing"]
        )

    def test_competitor_modes_and_workflow_contracts_are_explicit(self):
        condo_subject = agent_schemas.DailyMarketScanCompetitorSubject(
            property_id=17,
            competitor_mode="condo_same_building",
        )
        area_subject = agent_schemas.DailyMarketScanCompetitorSubject(
            listing_ref="manual:area-watch",
            competitor_mode="area_nearby_non_condo",
        )
        condo_scan = agent_schemas.DailyMarketScanCompetitorWatchScan(
            subject=condo_subject
        )
        area_scan = agent_schemas.DailyMarketScanCompetitorWatchScan(
            subject=area_subject
        )
        client_scan = agent_schemas.DailyMarketScanClientMatchScan(contact_id=42)

        self.assertEqual(condo_scan.workflow, "competitor_watch")
        self.assertEqual(condo_scan.subject.competitor_mode, "condo_same_building")
        self.assertEqual(area_scan.subject.competitor_mode, "area_nearby_non_condo")
        self.assertEqual(client_scan.workflow, "client_match")

    def test_public_listing_normalizer_extracts_and_dedupes_structured_records(self):
        page = build_public_page(
            "https://www.realtor.ca/real-estate/building-search",
            PUBLIC_LISTING_SEARCH_HTML,
        )

        normalized = public_listing_normalizer.normalize_public_listing_records(page)
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0].source_family, "realtor_ca_public")
        self.assertEqual(normalized[0].city, "Toronto")

        duplicated = normalized + [normalized[1]]
        deduped = public_listing_normalizer.dedupe_public_listing_records(duplicated)
        self.assertEqual(len(deduped), 3)

    def test_public_listing_provider_keeps_stub_only_without_contact_context(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_client_matches({"contact_id": 42})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.findings, [])
        self.assertIn("stub-only", " ".join(result.notes).lower())

    def test_public_listing_provider_returns_client_match_from_exact_public_reference(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_client_matches(
            {
                "contact": {
                    "contact_id": 42,
                    "budget_min": 800000,
                    "budget_max": 900000,
                    "preferred_areas": ["Toronto"],
                    "property_preferences": {"property_type": "condo"},
                },
                "candidate_properties": [
                    {
                        "property_id": 17,
                        "listing_url": "https://www.realtor.ca/real-estate/building-search",
                    }
                ],
            }
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].mls_number, "C7654321")
        self.assertEqual(result.findings[0].source_used, "public_listing:realtor_ca_public")
        self.assertIn("budget", " ".join(result.findings[0].why_it_matches).lower())

    def test_public_listing_provider_client_match_missing_reference_fails_soft(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_client_matches(
            {
                "contact": {
                    "contact_id": 42,
                    "budget_min": 800000,
                    "budget_max": 900000,
                    "preferred_areas": ["Toronto"],
                    "property_preferences": {"property_type": "condo"},
                },
                "candidate_properties": [],
                "candidate_listings": [],
            }
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_metadata[0].code, "public_reference_missing")

    def test_public_listing_provider_client_match_non_allowlisted_url_fails_soft(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_client_matches(
            {
                "contact": {
                    "contact_id": 42,
                    "budget_min": 800000,
                    "budget_max": 900000,
                    "preferred_areas": ["Toronto"],
                    "property_preferences": {"property_type": "condo"},
                },
                "candidate_properties": [
                    {"property_id": 17, "listing_url": "https://example.com/listing/17"}
                ],
            }
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            result.failure_metadata[0].code,
            "public_source_not_allowlisted",
        )

    def test_public_listing_provider_client_match_parse_no_records_fails_soft(self):
        provider = market_scan_providers.PublicListingProvider(
            fetch_page=fake_empty_realtor_fetch
        )

        result = provider.scan_client_matches(
            {
                "contact": {
                    "contact_id": 42,
                    "budget_min": 800000,
                    "budget_max": 900000,
                    "preferred_areas": ["Toronto"],
                    "property_preferences": {"property_type": "condo"},
                },
                "candidate_properties": [
                    {
                        "property_id": 17,
                        "listing_url": "https://www.realtor.ca/real-estate/building-search",
                    }
                ],
            }
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_metadata[0].code, "public_parse_no_records")

    def test_public_listing_provider_client_match_weak_match_returns_no_findings(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_client_matches(
            {
                "contact": {
                    "contact_id": 42,
                    "budget_min": 400000,
                    "budget_max": 500000,
                    "preferred_areas": ["North York"],
                    "property_preferences": {"property_type": "detached"},
                },
                "candidate_properties": [
                    {
                        "property_id": 17,
                        "listing_url": "https://www.realtor.ca/real-estate/building-search",
                    }
                ],
            }
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.findings, [])
        self.assertEqual(
            result.failure_metadata[-1].code,
            "public_client_match_confidence_low",
        )

    def test_public_listing_provider_returns_same_building_competitor_from_real_page(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_condo_competitors(
            {
                "property": {
                    "unit": "706",
                    "street": "20 Stewart St",
                    "city": "Toronto",
                    "postal_code": "M5V1B1",
                    "listing_url": "https://www.realtor.ca/real-estate/building-search",
                }
            }
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].mls_number, "C7654321")
        self.assertEqual(result.findings[0].source_used, "public_listing:realtor_ca_public")
        self.assertIn("same-building", " ".join(result.findings[0].competitor_notes).lower())

    def test_public_listing_provider_returns_area_competitor_with_postal_confidence(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_area_competitors(
            {
                "property": {
                    "street": "88 King St W",
                    "city": "Toronto",
                    "postal_code": "M5H1A1",
                    "listing_url": "https://www.realtor.ca/real-estate/area-search",
                }
            }
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].mls_number, "W9000001")
        self.assertIn("nearby-area", " ".join(result.findings[0].competitor_notes).lower())

    def test_public_listing_provider_fails_soft_when_public_reference_missing(self):
        provider = market_scan_providers.PublicListingProvider(fetch_page=fake_realtor_fetch)

        result = provider.scan_condo_competitors(
            {"property": {"street": "20 Stewart St", "city": "Toronto"}}
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_metadata[0].code, "public_reference_missing")


class DailyMarketScanRunnerTests(unittest.TestCase):
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

    def create_contact(
        self,
        name: str = "Daily Market Scan Contact",
        *,
        budget_min: float | None = None,
        budget_max: float | None = None,
        preferred_areas: str | None = None,
        property_preferences: str | None = None,
    ):
        contact = crm_models.Contact(
            name=name,
            client_type="buyer",
            status="active",
            budget_min=budget_min,
            budget_max=budget_max,
            preferred_areas=preferred_areas,
            property_preferences=property_preferences,
        )
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def create_property(
        self,
        *,
        property_type: str,
        street: str,
        unit: str | None = None,
        postal_code: str | None = None,
        neighborhood: str | None = None,
        listing_url: str | None = None,
    ):
        property_record = crm_models.Property(
            unit=unit,
            street=street,
            city="Toronto",
            postal_code=postal_code,
            neighborhood=neighborhood,
            property_type=property_type,
            status="listed_for_sale",
            listing_url=listing_url,
        )
        self.db.add(property_record)
        self.db.commit()
        self.db.refresh(property_record)
        return property_record

    def get_task(self, task_id: int):
        return (
            self.db.query(agent_models.AgentTask)
            .filter(agent_models.AgentTask.id == task_id)
            .first()
        )

    def get_audit_actions(self, run_id: int):
        return [
            log.action
            for log in self.db.query(agent_models.AgentAuditLog)
            .filter(agent_models.AgentAuditLog.run_id == run_id)
            .order_by(agent_models.AgentAuditLog.id.asc())
            .all()
        ]

    def test_db_backed_run_persists_plan_result_and_explicit_workflows(self):
        contact = self.create_contact()
        condo_property = self.create_property(property_type="condo", street="20 Stewart St")
        detached_property = self.create_property(
            property_type="detached", street="88 King St W"
        )

        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": StubPublicProvider(),
        }
        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "full_daily_scan",
                "run_mode": "manual_preview",
                "source_preference": "auto",
                "contact_ids": [contact.id],
                "property_ids": [condo_property.id, detached_property.id],
                "listing_refs": [
                    {
                        "listing_ref": "manual:listing:20-stewart",
                        "property_id": condo_property.id,
                        "label": "20 Stewart St #706",
                    }
                ],
            },
            provider_registry=provider_registry,
        )

        task = self.get_task(run.task_id)
        result = json.loads(run.result)
        plan = json.loads(run.plan)
        approvals = (
            self.db.query(agent_models.AgentApproval)
            .filter(agent_models.AgentApproval.run_id == run.id)
            .all()
        )

        self.assertEqual(task.agent_type, "daily_market_scan")
        self.assertEqual(task.status, "completed")
        self.assertEqual(run.status, "completed")
        self.assertEqual(approvals, [])
        self.assertEqual(plan["scope"]["decision"], "accepted")
        self.assertEqual(
            plan["provider_plan"]["provider_order"],
            ["authenticated_mls_browser", "public_listing"],
        )
        self.assertEqual(plan["selected_subjects"]["counts"]["contacts_selected"], 1)
        self.assertEqual(plan["selected_subjects"]["counts"]["properties_selected"], 2)
        self.assertEqual(plan["selected_subjects"]["counts"]["listings_selected"], 1)
        self.assertEqual(result["execution_policy"]["mode"], "internal_logging_review_only")
        self.assertFalse(result["execution_policy"]["can_auto_send"])
        self.assertEqual(len(result["client_match_scans"]), 1)
        self.assertEqual(len(result["competitor_watch_scans"]), 3)
        self.assertEqual(result["client_match_scans"][0]["status"], "completed")
        self.assertTrue(result["client_match_scans"][0]["fallback_used"])
        competitor_modes = [
            item["subject"]["competitor_mode"]
            for item in result["competitor_watch_scans"]
        ]
        self.assertIn("condo_same_building", competitor_modes)
        self.assertIn("area_nearby_non_condo", competitor_modes)
        self.assertEqual(
            result["competitor_watch_scans"][0]["source_attempts"][0]["provider_key"],
            "authenticated_mls_browser",
        )
        self.assertEqual(
            self.get_audit_actions(run.id),
            [
                "daily_market_scan_request_normalized",
                "daily_market_scan_subjects_resolved",
                "daily_market_scan_provider_plan_generated",
                "daily_market_scan_provider_execution_completed",
                "daily_market_scan_run_completed",
            ],
        )

    def test_no_providers_available_completes_fail_soft(self):
        contact = self.create_contact()
        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "auto",
                "contact_ids": [contact.id],
            },
            authenticated_mls_browser_availability="unavailable",
            public_availability="unavailable",
        )

        result = json.loads(run.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(result["client_match_scans"][0]["status"], "no_providers")
        self.assertIn(
            daily_market_scan.NO_PROVIDERS_AVAILABLE_RISK_FLAG,
            result["risk_flags"],
        )

    def test_provider_exception_is_captured_and_fallback_keeps_run_alive(self):
        contact = self.create_contact()
        provider_registry = {
            "authenticated_mls_browser": StubFailingAuthenticatedProvider(),
            "public_listing": StubPublicProvider(),
        }
        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "auto",
                "contact_ids": [contact.id],
            },
            provider_registry=provider_registry,
        )

        result = json.loads(run.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(result["client_match_scans"][0]["status"], "partial")
        self.assertIn(
            daily_market_scan.PROVIDER_FAILURE_RECORDED_RISK_FLAG,
            result["risk_flags"],
        )
        self.assertIn(
            daily_market_scan.PARTIAL_SCAN_RECORDED_RISK_FLAG,
            result["risk_flags"],
        )
        self.assertIn(
            "daily_market_scan_provider_failure_recorded",
            self.get_audit_actions(run.id),
        )

    def test_zero_findings_is_recorded_without_failing_run(self):
        contact = self.create_contact(
            budget_min=400000,
            budget_max=500000,
            preferred_areas='["North York"]',
            property_preferences='{"property_type":"detached"}',
        )
        condo_property = self.create_property(
            property_type="condo",
            street="20 Stewart St",
            unit="706",
            postal_code="M5V1B1",
            listing_url="https://www.realtor.ca/real-estate/building-search",
        )
        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": market_scan_providers.PublicListingProvider(
                fetch_page=fake_realtor_fetch
            ),
        }
        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "public_only",
                "contact_ids": [contact.id],
                "property_ids": [condo_property.id],
            },
            provider_registry=provider_registry,
        )

        result = json.loads(run.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(result["client_match_scans"][0]["status"], "no_findings")
        self.assertIn(
            daily_market_scan.ZERO_FINDINGS_RECORDED_RISK_FLAG,
            result["risk_flags"],
        )

    def test_client_match_real_public_provider_retrieval_is_constrained_and_persisted(self):
        contact = self.create_contact(
            budget_min=800000,
            budget_max=900000,
            preferred_areas='["Toronto"]',
            property_preferences='{"property_type":"condo"}',
        )
        condo_property = self.create_property(
            property_type="condo",
            street="20 Stewart St",
            unit="706",
            postal_code="M5V1B1",
            listing_url="https://www.realtor.ca/real-estate/building-search",
        )
        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": market_scan_providers.PublicListingProvider(
                fetch_page=fake_realtor_fetch
            ),
        }

        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "public_only",
                "contact_ids": [contact.id],
                "property_ids": [condo_property.id],
            },
            provider_registry=provider_registry,
        )

        result = json.loads(run.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(len(result["client_match_scans"]), 1)
        self.assertEqual(result["client_match_scans"][0]["status"], "completed")
        self.assertEqual(len(result["client_match_scans"][0]["findings"]), 1)
        self.assertEqual(
            result["client_match_scans"][0]["findings"][0]["source_used"],
            "public_listing:realtor_ca_public",
        )
        self.assertEqual(
            result["client_match_scans"][0]["source_attempts"][0]["provider_key"],
            "public_listing",
        )

    def test_route_surface_is_scoped_and_safe(self):
        contact = self.create_contact()
        run = agent_router.trigger_daily_market_scan_run_once(
            agent_schemas.DailyMarketScanRunRequest(
                scan_mode="client_match",
                run_mode="manual_preview",
                source_preference="public_only",
                contact_ids=[contact.id],
            ),
            db=self.db,
        )

        other_task = agent_service.create_task(self.db, agent_type="buyer_match")
        other_run = agent_service.create_run(
            self.db,
            task=other_task,
            summary="Not a daily market scan run",
        )
        other_run = agent_service.update_run_status(
            self.db,
            other_run,
            status="completed",
            result="{}",
        )

        runs = agent_router.list_daily_market_scan_runs(db=self.db)
        latest = agent_router.get_latest_daily_market_scan_result(db=self.db)
        report = agent_router.get_daily_market_scan_run_report(run.id, db=self.db)
        audit_logs = agent_router.list_daily_market_scan_run_audit_logs(run.id, db=self.db)

        self.assertEqual([item.id for item in runs], [run.id])
        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertIsNone(latest["error"])
        self.assertIsNotNone(latest["result"])
        self.assertEqual(report["execution_policy"]["mode"], "internal_logging_review_only")
        self.assertFalse(report["execution_policy"]["can_auto_send"])
        self.assertTrue(audit_logs)
        self.assertEqual(audit_logs[0].action, "daily_market_scan_request_normalized")

        with self.assertRaises(HTTPException) as report_error:
            agent_router.get_daily_market_scan_run_report(other_run.id, db=self.db)
        self.assertEqual(report_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as audit_error:
            agent_router.list_daily_market_scan_run_audit_logs(other_run.id, db=self.db)
        self.assertEqual(audit_error.exception.status_code, 404)

    def test_latest_route_returns_safe_empty_contract(self):
        latest = agent_router.get_latest_daily_market_scan_result(db=self.db)

        self.assertEqual(
            latest,
            {
                "run_id": None,
                "status": None,
                "error": None,
                "result": None,
            },
        )

    def test_latest_route_fails_soft_for_malformed_result(self):
        task = agent_service.create_task(self.db, agent_type="daily_market_scan")
        run = agent_service.create_run(
            self.db,
            task=task,
            summary="Malformed daily market scan result",
        )
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        latest = agent_router.get_latest_daily_market_scan_result(db=self.db)

        self.assertEqual(latest["run_id"], run.id)
        self.assertEqual(latest["status"], "completed")
        self.assertIsNone(latest["error"])
        self.assertIsNone(latest["result"])

    def test_report_route_returns_404_for_missing_structured_report(self):
        task = agent_service.create_task(self.db, agent_type="daily_market_scan")
        run = agent_service.create_run(
            self.db,
            task=task,
            summary="Malformed daily market scan result",
        )
        run = agent_service.update_run_status(
            self.db,
            run,
            status="completed",
            result="{not-json}",
        )

        with self.assertRaises(HTTPException) as report_error:
            agent_router.get_daily_market_scan_run_report(run.id, db=self.db)

        self.assertEqual(report_error.exception.status_code, 404)

    def test_competitor_watch_real_public_provider_retrieval_is_backend_only(self):
        condo_property = self.create_property(
            property_type="condo",
            street="20 Stewart St",
            unit="706",
            postal_code="M5V1B1",
            listing_url="https://www.realtor.ca/real-estate/building-search",
        )
        detached_property = self.create_property(
            property_type="detached",
            street="88 King St W",
            postal_code="M5H1A1",
            listing_url="https://www.realtor.ca/real-estate/area-search",
        )
        provider_registry = {
            "authenticated_mls_browser": StubAuthenticatedUnavailableProvider(),
            "public_listing": market_scan_providers.PublicListingProvider(
                fetch_page=fake_realtor_fetch
            ),
        }

        run = daily_market_scan.run_daily_market_scan_once(
            self.db,
            {
                "scan_mode": "competitor_watch",
                "run_mode": "manual_preview",
                "source_preference": "public_only",
                "property_ids": [condo_property.id, detached_property.id],
            },
            provider_registry=provider_registry,
        )

        result = json.loads(run.result)
        self.assertEqual(run.status, "completed")
        self.assertEqual(len(result["client_match_scans"]), 0)
        self.assertEqual(len(result["competitor_watch_scans"]), 2)
        modes = [
            item["subject"]["competitor_mode"]
            for item in result["competitor_watch_scans"]
        ]
        self.assertEqual(
            modes,
            ["condo_same_building", "area_nearby_non_condo"],
        )
        first_findings = result["competitor_watch_scans"][0]["findings"]
        second_findings = result["competitor_watch_scans"][1]["findings"]
        self.assertEqual(len(first_findings), 1)
        self.assertEqual(len(second_findings), 1)
        self.assertEqual(first_findings[0]["source_used"], "public_listing:realtor_ca_public")
        self.assertEqual(second_findings[0]["source_used"], "public_listing:realtor_ca_public")
        self.assertNotIn(
            daily_market_scan.ZERO_FINDINGS_RECORDED_RISK_FLAG,
            result["risk_flags"],
        )


if __name__ == "__main__":
    unittest.main()
