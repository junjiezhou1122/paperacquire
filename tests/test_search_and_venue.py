from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from paperacquire import cli
from paperacquire import search
from paperacquire.index import get_record
from paperacquire.models import SearchResult
from paperacquire.sources import openreview_adaptive


class SearchProviderTests(unittest.TestCase):
    def test_search_registry_includes_conference_sources(self):
        self.assertIn("dblp", search.PROVIDERS)
        self.assertIn("openreview", search.PROVIDERS)


class OpenReviewVenueTests(unittest.TestCase):
    def test_conference_name_normalization_preserves_acronyms(self):
        self.assertEqual(openreview_adaptive._build_invitation("iclr", 2025, None), "ICLR.cc/2025/Conference/-/Submission")
        self.assertEqual(openreview_adaptive._build_invitation("NeurIPS", 2025, None), "NeurIPS.cc/2025/Conference/-/Submission")


class VenueCliTests(unittest.TestCase):
    def test_venue_search_combines_and_dedupes_sources(self):
        def openreview_provider(conference, year, limit=25):
            return [
                SearchResult(
                    title="A Useful Conference Paper",
                    source="openreview",
                    sources=["openreview"],
                    identifiers={"openreview_id": "abc123"},
                    year=year,
                    venue=conference,
                    canonical_url="https://openreview.net/forum?id=abc123",
                )
            ]

        def dblp_provider(conference, year, limit=25):
            return [
                SearchResult(
                    title="A Useful Conference Paper",
                    source="dblp",
                    sources=["dblp"],
                    identifiers={"dblp_key": "conf/iclr/Example25"},
                    year=year,
                    venue=conference,
                    canonical_url="https://dblp.org/rec/conf/iclr/Example25",
                )
            ]

        with patch.dict(cli.VENUE_PROVIDERS, {"openreview": openreview_provider, "dblp": dblp_provider}, clear=True):
            results = cli.search_venue_papers("ICLR", 2025, limit=10, source="all")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "A Useful Conference Paper")
        self.assertEqual(results[0]["sources"], ["dblp", "openreview"])

    def test_ingest_search_candidates_writes_metadata_only_record(self):
        old_home = os.environ.get("PAPER_ACQUIRE_HOME")
        with TemporaryDirectory() as tmp:
            try:
                os.environ["PAPER_ACQUIRE_HOME"] = tmp
                summary = cli._ingest_search_candidates(
                    [
                        {
                            "title": "OpenReview Only Paper",
                            "source": "openreview",
                            "sources": ["openreview"],
                            "identifiers": {"openreview_id": "xyz789"},
                            "venue": "ICLR",
                            "year": 2025,
                            "canonical_url": "https://openreview.net/forum?id=xyz789",
                        }
                    ],
                    source_input="venue:ICLR:2025:openreview",
                )
                record = get_record("openreview:xyz789")
            finally:
                if old_home is not None:
                    os.environ["PAPER_ACQUIRE_HOME"] = old_home
                else:
                    os.environ.pop("PAPER_ACQUIRE_HOME", None)

        self.assertEqual(summary["new_papers"], ["openreview:xyz789"])
        self.assertIsNotNone(record)
        self.assertEqual(record["title"], "OpenReview Only Paper")
        self.assertEqual(record["venue"], "ICLR")


if __name__ == "__main__":
    unittest.main()
