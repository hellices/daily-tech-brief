import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "briefing.py"


def example_issue():
    return {
        "schema_version": 1,
        "date": "2026-09-16",
        "generated_at": "2026-09-16T08:30:00+09:00",
        "headline": "Local test fixture, not a real briefing",
        "summary": ["Fixture summary one", "Fixture summary two", "Fixture summary three"],
        "coverage": {
            name: {
                "status": "partial",
                "note": "Local fixture with fewer items; not for publication.",
                "sources": ["https://example.org/source"],
            }
            for name in ("github", "papers", "community", "cncf")
        },
        "github_snapshot": {
            "captured_at": "2026-09-16T08:00:00+09:00",
            "source": "https://github.com/trending?since=weekly",
            "entries": [{"repository": "fixture/tool", "rank": 1, "weekly_stars": 12}],
        },
        "repositories": [{
            "repository": "fixture/tool",
            "url": "https://github.com/fixture/tool",
            "rank": 1,
            "summary": "A fixture repository.",
            "why_now": "A fixture trend.",
            "use_case": "Unit testing only.",
            "caution": "Not a real recommendation.",
            "sources": ["https://github.com/fixture/tool"],
        }],
        "papers": [{
            "id": "arxiv:2609.00001v2",
            "title": "Fixture paper",
            "url": "https://arxiv.org/abs/2609.00001",
            "first_published": "2026-09-01",
            "topics": ["memory", "evaluation"],
            "evidence": "full_text",
            "abstract_summary": "A fixture abstract summary.",
            "method": "A fixture method.",
            "findings": "A fixture reported result.",
            "limitations": "Not a real paper.",
            "practical_value": "Unit testing only.",
            "sources": ["https://arxiv.org/abs/2609.00001"],
        }],
        "discussions": [{
            "title": "Fixture discussion",
            "url": "https://example.org/story",
            "summary": "A fixture discussion summary.",
            "significance": "Unit testing only.",
            "caveat": "Not a real story.",
            "sources": ["https://news.ycombinator.com/item?id=1"],
        }],
        "cncf": [{
            "title": "Fixture release",
            "url": "https://example.org/release",
            "published": "2026-09-15",
            "category": "release",
            "summary": "A fixture release summary.",
            "impact": "Unit testing only.",
            "sources": ["https://example.org/release"],
        }],
    }


class BriefingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briefing = None
        if MODULE_PATH.exists():
            spec = importlib.util.spec_from_file_location("briefing", MODULE_PATH)
            cls.briefing = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.briefing)

    def api(self):
        self.assertIsNotNone(self.briefing, "The briefing pipeline is not implemented yet")
        return self.briefing

    def test_six_calendar_months_handles_month_end(self):
        b = self.api()
        self.assertEqual(b.six_months_before("2026-08-31"), "2026-02-28")
        self.assertEqual(b.six_months_before("2026-09-16"), "2026-03-16")

    def test_arxiv_versions_and_doi_links_have_canonical_ids(self):
        b = self.api()
        self.assertEqual(b.canonical_paper_id("arxiv:2609.00001v2"), "arxiv:2609.00001")
        self.assertEqual(b.canonical_paper_id("https://arxiv.org/pdf/2609.00001v3.pdf"), "arxiv:2609.00001")
        self.assertEqual(b.canonical_paper_id("https://doi.org/10.1234/ABC"), "doi:10.1234/abc")

    def test_first_run_does_not_claim_historical_new_entry(self):
        b = self.api()
        context = b.context_for("2026-09-16", b.empty_state())
        self.assertIsNone(context["previous_snapshot"])
        self.assertTrue(context["first_run"])
        self.assertEqual(context["paper_first_publication_cutoff"], "2026-03-16")

    def test_fixture_validates_but_old_and_future_papers_fail(self):
        b = self.api()
        b.validate_issue(example_issue(), b.empty_state())
        for published in ("2026-03-15", "2026-09-17"):
            issue = example_issue()
            issue["papers"][0]["first_published"] = published
            with self.assertRaisesRegex(ValueError, "six-month"):
                b.validate_issue(issue, b.empty_state())

    def test_repository_history_is_case_insensitive_and_permanent(self):
        b = self.api()
        state = b.empty_state()
        state["introduced"]["repositories"]["fixture/tool"] = "2026-01-01"
        issue = example_issue()
        issue["repositories"][0]["repository"] = "Fixture/Tool"
        with self.assertRaisesRegex(ValueError, "already introduced"):
            b.validate_issue(issue, state)

    def test_paper_exclusion_is_seven_days_and_version_independent(self):
        b = self.api()
        state = b.empty_state()
        state["introduced"]["papers"]["arxiv:2609.00001"] = "2026-09-10"
        with self.assertRaisesRegex(ValueError, "last seven days"):
            b.validate_issue(example_issue(), state)
        state["introduced"]["papers"]["arxiv:2609.00001"] = "2026-09-08"
        b.validate_issue(example_issue(), state)

    def test_same_issue_can_be_published_after_teams_delivery(self):
        b = self.api()
        state = b.empty_state()
        b.introduce(example_issue(), state)
        b.validate_issue(example_issue(), state)

    def test_new_entry_embeds_comparison_evidence_for_static_build(self):
        b = self.api()
        issue = example_issue()
        state = b.empty_state()
        previous = copy.deepcopy(issue["github_snapshot"])
        previous["captured_at"] = "2026-09-15T08:00:00+09:00"
        previous["entries"][0]["repository"] = "fixture/other"
        state["observations"]["2026-09-15"] = previous
        issue["repositories"][0]["novelty"] = "new_entry"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            b.save_state(root, state)
            b.stage_issue(root, issue)
            staged = b.load_draft(root, "2026-09-16")
            self.assertEqual(staged["github_previous_snapshot"], previous)
            b.validate_issue(staged, b.empty_state())

    def test_publication_history_only_changes_after_confirmed_deployment(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = example_issue()
            b.stage_issue(root, issue)
            b.promote_issue(root, issue["date"], b.issue_digest(issue))
            self.assertEqual(b.load_state(root)["introduced"]["repositories"], {})
            b.record_publication(root, issue["date"], b.issue_digest(issue))
            self.assertIn("fixture/tool", b.load_state(root)["introduced"]["repositories"])

    def test_duplicate_paper_versions_within_issue_fail(self):
        b = self.api()
        issue = example_issue()
        paper = copy.deepcopy(issue["papers"][0])
        paper["id"] = "https://arxiv.org/abs/2609.00001v4"
        issue["papers"].append(paper)
        with self.assertRaisesRegex(ValueError, "Duplicate paper"):
            b.validate_issue(issue, b.empty_state())

    def test_repository_must_match_real_snapshot_rank(self):
        b = self.api()
        issue = example_issue()
        issue["repositories"][0]["rank"] = 2
        with self.assertRaisesRegex(ValueError, "snapshot"):
            b.validate_issue(issue, b.empty_state())

    def test_snapshot_source_must_really_be_weekly_github_trending(self):
        b = self.api()
        issue = example_issue()
        issue["github_snapshot"]["source"] = "https://github.com/trending?since=daily"
        with self.assertRaisesRegex(ValueError, "weekly"):
            b.validate_issue(issue, b.empty_state())

    def test_fewer_papers_and_partial_source_failures_need_explanation(self):
        b = self.api()
        issue = example_issue()
        issue["coverage"]["papers"]["note"] = ""
        with self.assertRaisesRegex(ValueError, "note"):
            b.validate_issue(issue, b.empty_state())

    def test_unsafe_urls_and_naive_timestamps_fail(self):
        b = self.api()
        for url in ("javascript:alert(1)", "https://user:secret@example.org", "https://example.org/\nfoo"):
            issue = example_issue()
            issue["papers"][0]["url"] = url
            with self.assertRaises(ValueError):
                b.validate_issue(issue, b.empty_state())
        issue = example_issue()
        issue["generated_at"] = "2026-09-16T08:30:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            b.validate_issue(issue, b.empty_state())

    def test_cncf_changes_stay_in_three_day_window(self):
        b = self.api()
        issue = example_issue()
        issue["cncf"][0]["published"] = "2026-08-01"
        with self.assertRaisesRegex(ValueError, "three-day"):
            b.validate_issue(issue, b.empty_state())

    def test_delivery_is_utf8_bounded_and_contains_full_paper(self):
        b = self.api()
        issue = example_issue()
        issue["papers"][0]["method"] = "긴 한글 문장입니다. " * 300
        parts = b.delivery_parts(issue, max_bytes=1800)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p.encode("utf-8")) <= 1800 for p in parts))
        self.assertIn("A fixture reported result.", "".join(parts))
        self.assertIn("Not a real paper.", "".join(parts))
        self.assertIn("https://arxiv.org/abs/2609.00001", "".join(parts))

    def test_normal_source_links_are_not_split_across_delivery_parts(self):
        b = self.api()
        issue = example_issue()
        issue["papers"][0]["method"] = "Long method. " * 80
        url = "https://example.org/" + "long-url-segment" * 12
        issue["papers"][0]["sources"] = [url]
        parts = b.delivery_parts(issue, max_bytes=1800)
        self.assertTrue(any(url in part for part in parts))

    def test_delivery_rejects_unexpected_public_payload_fields(self):
        b = self.api()
        issue = example_issue()
        issue["private_notes"] = "This should never be published"
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            b.validate_issue(issue, b.empty_state())
        issue = example_issue()
        issue["papers"][0]["private_notes"] = "Never publish extra fields"
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            b.validate_issue(issue, b.empty_state())

    def test_receipts_update_history_only_when_all_parts_succeed(self):
        b = self.api()
        state = b.empty_state()
        issue = example_issue()
        issue["papers"][0]["method"] = "검증용 긴 본문입니다. " * 1000
        digest = b.issue_digest(issue)
        parts = b.delivery_parts(issue)
        self.assertGreater(len(parts), 1)
        state = b.record_receipt(issue, state, digest, 0, len(parts))
        if len(parts) > 1:
            self.assertNotIn("fixture/tool", state["introduced"]["repositories"])
        for index in range(1, len(parts)):
            state = b.record_receipt(issue, state, digest, index, len(parts))
        self.assertEqual(state["introduced"]["repositories"]["fixture/tool"], "2026-09-16")
        again = b.record_receipt(issue, state, digest, 0, len(parts))
        self.assertEqual(again, state)
        with self.assertRaisesRegex(ValueError, "digest"):
            b.record_receipt(issue, state, "wrong", 0, len(parts))

    def test_stage_never_marks_items_introduced_and_blocks_receipted_rewrites(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = example_issue()
            b.stage_issue(root, issue)
            self.assertEqual(b.load_state(root)["introduced"]["repositories"], {})
            state = b.load_state(root)
            state = b.record_receipt(issue, state, b.issue_digest(issue), 0, len(b.delivery_parts(issue)))
            b.save_state(root, state)
            issue["headline"] = "Changed after sending"
            with self.assertRaisesRegex(ValueError, "delivery"):
                b.stage_issue(root, issue)

    def test_publication_requires_exact_approved_digest(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            b.stage_issue(root, example_issue())
            with self.assertRaisesRegex(ValueError, "digest"):
                b.promote_issue(root, "2026-09-16", "incorrect")
            self.assertFalse((root / "reports" / "2026-09-16.json").exists())
            b.promote_issue(root, "2026-09-16", b.issue_digest(example_issue()))
            self.assertTrue((root / "reports" / "2026-09-16.json").exists())

    def test_html_escapes_external_content_and_keeps_original_links(self):
        b = self.api()
        issue = example_issue()
        issue["headline"] = "<script>alert('bad')</script>"
        body = b.render_issue(issue)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("https://arxiv.org/abs/2609.00001", body)
        self.assertIn('<details class="paper-details">', body)
        self.assertIn('data-issue-digest="' + b.issue_digest(issue) + '"', body)
        for section in ("github", "papers", "community", "cncf"):
            self.assertIn('id="' + section + '"', body)

    def test_build_only_includes_promoted_reports_not_drafts(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "template.html").write_text(
                "<title>@@TITLE@@</title><a href='@@BASE@@index.html'>Home</a>@@CONTENT@@",
                encoding="utf-8",
            )
            b.stage_issue(root, example_issue())
            b.build_site(root)
            homepage = (root / "site" / "index.html").read_text(encoding="utf-8")
            self.assertIn("첫 보고서", homepage)
            self.assertNotIn("Fixture paper", homepage)
            b.promote_issue(root, "2026-09-16", b.issue_digest(example_issue()))
            b.build_site(root)
            page = root / "site" / "daily" / "2026-09-16" / "index.html"
            self.assertTrue(page.exists())
            self.assertIn("Fixture paper", page.read_text(encoding="utf-8"))
            self.assertIn("<title>2026-09-16 · Local test fixture, not a real briefing</title>",
                          page.read_text(encoding="utf-8"))
            self.assertIn("<h1>2026-09-16 · Local test fixture, not a real briefing</h1>",
                          page.read_text(encoding="utf-8"))
            self.assertNotIn(".local", (root / "site" / "index.html").read_text(encoding="utf-8"))
            (root / "reports" / "2026-09-16.json").unlink()
            b.build_site(root)
            self.assertFalse(page.exists(), "Removed reports must not linger in deployment output")

    def test_daily_archive_accumulates_latest_first_without_overwriting_older_issues(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "template.html").write_text(
                "<title>@@TITLE@@</title><a href='@@BASE@@index.html'>Home</a>@@CONTENT@@",
                encoding="utf-8",
            )
            first = example_issue()
            b.stage_issue(root, first)
            b.promote_issue(root, first["date"], b.issue_digest(first))
            original = (root / "reports" / "2026-09-16.json").read_bytes()
            b.build_site(root)
            first_page = root / "site" / "daily" / "2026-09-16" / "index.html"
            original_page = first_page.read_bytes()

            second = example_issue()
            second["date"] = "2026-09-17"
            second["generated_at"] = "2026-09-17T08:30:00+09:00"
            second["github_snapshot"]["captured_at"] = "2026-09-17T08:00:00+09:00"
            second["repositories"] = []
            second["papers"] = []
            b.stage_issue(root, second)
            staged_second = b.load_draft(root, second["date"])
            b.promote_issue(root, second["date"], b.issue_digest(staged_second))
            self.assertEqual(b.build_site(root), 2)

            self.assertEqual((root / "reports" / "2026-09-16.json").read_bytes(), original)
            self.assertEqual(first_page.read_bytes(), original_page)
            homepage = (root / "site" / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="./daily/2026-09-16/index.html"', homepage)
            self.assertIn('href="./daily/2026-09-17/index.html"', homepage)
            self.assertLess(homepage.index("2026-09-17"), homepage.index("2026-09-16"))
            self.assertIn(">2026-09-17 · Local test fixture, not a real briefing</a>", homepage)


if __name__ == "__main__":
    unittest.main()
