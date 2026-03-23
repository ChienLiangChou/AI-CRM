import unittest

from app.agents import event_strategy_review
from app.agents import event_strategy_review_retrieval


class StubCuratedSearchAdapter(
    event_strategy_review_retrieval.BaseCuratedSearchAdapter
):
    adapter_key = "stub_curated_search"

    def __init__(self, *, status="success", candidates=None, notes=None):
        self._status = status
        self._candidates = tuple(candidates or [])
        self._notes = tuple(notes or [])

    def search(self, *, query: str, max_results: int, allowed_domains: list[str]):
        return event_strategy_review_retrieval.CuratedSearchAdapterResponse(
            status=self._status,
            candidates=self._candidates,
            notes=self._notes,
        )


class EventStrategyReviewRetrievalTests(unittest.TestCase):
    def normalized_request(self, payload):
        return event_strategy_review.normalize_run_request(
            {
                "retrieval_contract": {
                    "source_mode": "curated_search_query",
                    "curated_search_query_input": payload,
                }
            }
        )

    def test_unavailable_adapter_fails_soft_with_default_trusted_policy(self):
        request = self.normalized_request(
            {
                "query": "Toronto housing policy",
                "max_results": 10,
            }
        )

        outcome = event_strategy_review_retrieval.run_curated_search_query(
            request,
            adapter=StubCuratedSearchAdapter(status="unavailable"),
        )

        self.assertEqual(outcome.execution_status, "retrieval_unavailable")
        self.assertEqual(outcome.retrieval_metadata.retrieval_state, "retrieval_unavailable")
        self.assertTrue(outcome.retrieval_metadata.default_trusted_domain_policy_applied)
        self.assertEqual(outcome.retrieval_metadata.raw_candidate_cap, 8)
        self.assertEqual(outcome.retrieval_metadata.fetched_source_cap, 3)
        self.assertFalse(outcome.sources)

    def test_rate_limited_adapter_fails_soft_without_fake_success(self):
        request = self.normalized_request(
            {
                "query": "Toronto mortgage rates",
                "allowed_domains": ["bankofcanada.ca"],
            }
        )

        outcome = event_strategy_review_retrieval.run_curated_search_query(
            request,
            adapter=StubCuratedSearchAdapter(status="rate_limited"),
        )

        self.assertEqual(outcome.execution_status, "rate_limited")
        self.assertEqual(outcome.retrieval_metadata.retrieval_state, "rate_limited")
        self.assertEqual(outcome.retrieval_metadata.allowed_domains_applied, ["bankofcanada.ca"])
        self.assertFalse(outcome.sources)

    def test_allowed_domains_and_trust_filter_can_end_in_no_credible_sources(self):
        request = self.normalized_request(
            {
                "query": "Toronto condo blog chatter",
                "allowed_domains": ["example-blog.com"],
            }
        )
        adapter = StubCuratedSearchAdapter(
            candidates=[
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://example-blog.com/post",
                    title="Condo chatter",
                    snippet="Untrusted source should not survive trust filtering.",
                )
            ]
        )

        outcome = event_strategy_review_retrieval.run_curated_search_query(
            request,
            adapter=adapter,
        )

        self.assertEqual(outcome.execution_status, "no_credible_sources")
        self.assertEqual(outcome.retrieval_metadata.retrieval_state, "no_credible_sources")
        self.assertEqual(outcome.retrieval_metadata.allowed_domains_applied, ["example-blog.com"])
        self.assertFalse(outcome.sources)

    def test_candidate_caps_and_source_caps_are_enforced(self):
        request = self.normalized_request(
            {
                "query": "Toronto housing policy and rates",
                "allowed_domains": [
                    "bankofcanada.ca",
                    "toronto.ca",
                    "cbc.ca",
                    "reuters.com",
                ],
                "max_results": 20,
            }
        )
        adapter = StubCuratedSearchAdapter(
            candidates=[
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://bankofcanada.ca/a",
                    title="Bank of Canada A",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://bankofcanada.ca/a?utm_source=x",
                    title="Bank of Canada duplicate",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://toronto.ca/b",
                    title="Toronto policy B",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://cbc.ca/c",
                    title="CBC C",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://reuters.com/d",
                    title="Reuters D",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://reuters.com/e",
                    title="Reuters E",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://toronto.ca/f",
                    title="Toronto F",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://cbc.ca/g",
                    title="CBC G",
                ),
                event_strategy_review_retrieval.CuratedSearchCandidate(
                    url="https://cbc.ca/h",
                    title="CBC H should be capped out",
                ),
            ]
        )

        outcome = event_strategy_review_retrieval.run_curated_search_query(
            request,
            adapter=adapter,
        )

        self.assertEqual(outcome.execution_status, "report_generated")
        self.assertEqual(outcome.retrieval_metadata.raw_candidate_count, 8)
        self.assertEqual(outcome.retrieval_metadata.fetched_source_count, 3)
        self.assertLessEqual(len(outcome.sources), 3)
        self.assertEqual(
            len({source.source_domain for source in outcome.sources if source.source_domain}),
            outcome.retrieval_metadata.independent_source_count,
        )
        self.assertTrue(
            all(
                source.source_domain
                in {"bankofcanada.ca", "toronto.ca", "cbc.ca", "reuters.com"}
                for source in outcome.sources
            )
        )


if __name__ == "__main__":
    unittest.main()
