import unittest

from app.agents import daily_market_scan
from app.agents import market_scan_providers
from app.agents import schemas as agent_schemas


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
                    code="stratus_unavailable",
                    message="Primary source unavailable; fallback used.",
                    retryable=True,
                    fallback_attempted=True,
                    fallback_used=True,
                )
            ],
            notes=["Stub fallback result."],
        )


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
            stratus_auth_state="expired",
            stratus_availability="limited",
            public_availability="available",
        )

        self.assertEqual([item.provider_key for item in catalog], ["stratus_authenticated", "public_listing"])
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
                "source_preference": "stratus_first",
                "contact_ids": list(range(1, 40)),
            },
            stratus_auth_state="unauthenticated",
            stratus_availability="limited",
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
            "Any external-facing draft from this layer remains review-only and is never auto-sent.",
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
        self.assertEqual(scan_result.failure_metadata[0].code, "stratus_unavailable")
        self.assertEqual(source_attempt.source_used, "stub_public")
        self.assertTrue(source_attempt.fallback_used)
        self.assertEqual(source_attempt.failure_metadata[0].provider_key, "public_listing")

    def test_public_only_preference_excludes_stratus_from_provider_order(self):
        result = daily_market_scan.build_scan_result_contract(
            {
                "scan_mode": "client_match",
                "run_mode": "manual_preview",
                "source_preference": "public_only",
                "contact_ids": [42],
            }
        )

        self.assertEqual(result.scan_summary.provider_order, ["public_listing"])
        self.assertEqual([item.provider_key for item in result.provider_catalog], ["public_listing"])


if __name__ == "__main__":
    unittest.main()
