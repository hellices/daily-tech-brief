import copy
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "briefing.py"


def example_issue():
    return {
        "schema_version": 2,
        "lead": {"section": "papers", "url": "https://arxiv.org/abs/2609.00001"},
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
            "tags": ["agent", "developer-tools"],
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
            "tags": ["evaluation", "memory"],
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
            "tags": ["developer-tools"],
            "url": "https://example.org/story",
            "sources": ["https://news.ycombinator.com/item?id=1"],
        }],
        "cncf": [{
            "title": "Fixture release",
            "tags": ["kubernetes", "release"],
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

    def test_delivery_does_not_claim_an_approved_report_is_still_waiting(self):
        b = self.api()
        message = b.report_text(example_issue())
        self.assertNotIn("공개 게시 대기:", message)
        self.assertIn("https://hellices.github.io/daily-tech-brief/", message)
        self.assertIn("아직 공개하지 않은 보고서는", message)

    def test_delivery_instructions_use_only_the_resolved_self_chat(self):
        instructions = (MODULE_PATH.parent / "automation-deliver.txt").read_text(encoding="utf-8")
        self.assertIn("workiq_create_chat_by_email", instructions)
        self.assertIn("48:notes", instructions)
        self.assertIn("workiq_send_chat_message", instructions)
        self.assertNotIn("m_send_teams_message", instructions)
        self.assertNotIn("m_relay_status", instructions)
        self.assertIn('contentType="html"', instructions)
        self.assertIn("briefing.py digest", instructions)
        self.assertIn("briefing.py record-digest", instructions)

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
            second["lead"] = {"section": "cncf", "url": second["cncf"][0]["url"]}
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

    def test_tags_normalize_aliases_and_reject_unknown_or_excessive_tags(self):
        b = self.api()
        self.assertEqual(b.normalize_tags([" Memory ", "메모리", "AGENTS", "agent"]), ["agent", "memory"])
        self.assertEqual(b.normalize_tags(["k8s", "쿠버네티스"]), ["kubernetes"])
        for tags in ([], ["made-up-tag"], "memory",
                     ["agent", "memory", "harness", "evaluation", "kubernetes", "security"]):
            with self.assertRaises(ValueError):
                b.normalize_tags(tags)

    def test_tag_registry_has_unique_stable_ids_and_unambiguous_aliases(self):
        b = self.api()
        entries = b.TAXONOMY["tags"]
        self.assertEqual(b.TAXONOMY["version"], 1)
        self.assertEqual(len(entries), len(b.TAGS))
        for entry in entries:
            self.assertRegex(entry["id"], r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
            for name in [entry["id"], entry["label"], *entry["aliases"]]:
                self.assertEqual(b.normalize_tags([name]), [entry["id"]])

    def test_staging_requires_tags_for_every_new_item_and_normalizes_them(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = example_issue()
            del issue["papers"][0]["tags"]
            with self.assertRaisesRegex(ValueError, "tags"):
                b.stage_issue(root, issue)
            issue["papers"][0]["tags"] = ["메모리", "eval", "Memory"]
            b.stage_issue(root, issue)
            self.assertEqual(b.load_draft(root, issue["date"])["papers"][0]["tags"],
                             ["evaluation", "memory"])

    def test_legacy_untagged_reports_remain_readable_and_searchable(self):
        b = self.api()
        issue = example_issue()
        issue["schema_version"] = 1
        issue.pop("lead")
        issue["discussions"][0].update(summary="Legacy summary", significance="Legacy relevance", caveat="Legacy caveat")
        for name in ("repositories", "papers", "discussions", "cncf"):
            for item in issue[name]:
                del item["tags"]
        b.validate_issue(issue, b.empty_state())
        index = b.build_search_index([issue])
        self.assertEqual(len(index["items"]), 4)
        self.assertTrue(all(item["tags"] == [] for item in index["items"]))
        self.assertEqual(index["tags"], [])

    def test_item_links_and_search_index_cover_all_sections_and_paper_details(self):
        b = self.api()
        issue = example_issue()
        index = b.build_search_index([issue])
        self.assertEqual({item["section"] for item in index["items"]},
                         {"github", "papers", "community", "cncf"})
        self.assertEqual(len({item["id"] for item in index["items"]}), 4)
        rendered = b.render_issue(issue)
        for item in index["items"]:
            anchor = item["href"].split("#")[1]
            self.assertIn('id="' + anchor + '"', rendered)
            self.assertTrue(item["href"].startswith("./daily/2026-09-16/index.html#item-"))
        paper = next(item for item in index["items"] if item["section"] == "papers")
        self.assertIn("A fixture reported result.", paper["body"])
        self.assertIn("Not a real paper.", paper["body"])
        self.assertIn("메모리", paper["search_text"])
        self.assertIn("memory", paper["search_text"])
        self.assertIn("Fixture summary one", paper["search_text"])
        self.assertIn("../../index.html#tag=memory", rendered)
        self.assertIn("태그:", b.report_text(issue))
        self.assertEqual(next(tag["count"] for tag in index["tags"] if tag["id"] == "developer-tools"), 2)

    def test_search_data_is_escaped_and_anchors_do_not_depend_on_item_order(self):
        b = self.api()
        issue = example_issue()
        item = issue["papers"][0]
        anchor = b.item_anchor("papers", item)
        item["title"] = "A changed editorial title"
        self.assertEqual(b.item_anchor("papers", item), anchor)
        issue["headline"] = "</script><script>alert('external content')</script>"
        page = b.render_home([issue])
        self.assertNotIn("</script><script>alert", page)
        self.assertIn("\\u003c/script>", page)
        self.assertIn('id="search-form"', page)
        self.assertIn('id="search-section"', page)
        self.assertIn('id="search-from"', page)
        self.assertIn('id="search-to"', page)
        self.assertIn('id="date-archive"', page)
        self.assertIn('name="tag" value="memory"', page)
        self.assertIn("./index.html#tag=memory", page)
        payload = re.search(r'<script id="search-data" type="application/json">(.*?)</script>', page, re.S)
        self.assertIsNotNone(payload)
        parsed = json.loads(payload.group(1))
        self.assertEqual(parsed["items"][0]["issue_title"], b.issue_title(issue))
        self.assertEqual({item["section"] for item in parsed["items"]}, set(b.SECTIONS))

    def test_empty_daily_issue_still_counts_as_a_public_report(self):
        b = self.api()
        issue = example_issue()
        for name in b.ITEM_COLLECTIONS.values():
            issue[name] = []
        issue["lead"] = None
        b.validate_issue(issue, b.empty_state())
        index = b.build_search_index([issue])
        self.assertEqual(index["report_dates"], ["2026-09-16"])
        self.assertEqual(index["items"], [])
        self.assertEqual(index["tags"], [])

    def test_new_papers_require_full_text_but_legacy_reports_preserve_caveats(self):
        b = self.api()
        issue = example_issue()
        issue["papers"][0]["evidence"] = "abstract_only"
        with self.assertRaisesRegex(ValueError, "full text"):
            b.validate_issue(issue, b.empty_state())
        issue["schema_version"] = 1
        issue.pop("lead")
        issue["discussions"][0].update(summary="Legacy", significance="Legacy", caveat="Legacy")
        b.validate_issue(issue, b.empty_state())
        self.assertIn("초록만 확인", b.render_issue(issue))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "version 2"):
                b.stage_issue(Path(folder), issue)

    def test_editorial_lead_references_one_real_item_and_has_top_priority(self):
        b = self.api()
        issue = example_issue()
        issue["headline"] = "The one standout result"
        body = b.render_issue(issue)
        self.assertIn('class="lead-story"', body)
        self.assertIn('href="#' + b.item_anchor("papers", issue["papers"][0]) + '"', body)
        self.assertLess(body.index('class="lead-story"'), body.index('id="github"'))
        self.assertIn("Technical Spotlight", b.report_text(issue))
        self.assertIn("Technical Spotlight", body)
        self.assertNotIn("오늘의 한 가지", body)
        self.assertNotIn("오늘의 한 가지", b.report_text(issue))
        index = b.build_search_index([issue])
        lead_result = next(item for item in index["items"] if item["section"] == "papers")
        self.assertIn("The one standout result", lead_result["search_text"])
        for item in index["items"]:
            if item["section"] != "papers":
                self.assertNotIn("The one standout result", item["search_text"])
        issue["lead"]["url"] = "https://arxiv.org/abs/2609.99999"
        with self.assertRaisesRegex(ValueError, "lead"):
            b.validate_issue(issue, b.empty_state())

    def test_community_is_a_link_list_in_html_and_teams(self):
        b = self.api()
        issue = example_issue()
        issue["discussions"][0]["sources"].insert(0, issue["discussions"][0]["url"])
        b.validate_issue(issue, b.empty_state())
        html = b.render_issue(issue)
        section = html.split('<section id="community">')[1].split("</section>")[0]
        self.assertIn("Fixture discussion", section)
        self.assertIn("https://example.org/story", section)
        self.assertIn("https://news.ycombinator.com/item?id=1", section)
        self.assertNotIn("<dl>", section)
        self.assertEqual(section.count('href="https://example.org/story"'), 1)
        message = b.report_text(issue).split("HN · 긱뉴스 · Reddit")[1].split("\nCNCF")[0]
        self.assertIn("Fixture discussion", message)
        self.assertNotIn("사실과 의견:", message)
        self.assertEqual(message.count("https://example.org/story"), 1)
        issue["discussions"][0]["summary"] = "Unwanted explanation"
        with self.assertRaisesRegex(ValueError, "link-only"):
            b.validate_issue(issue, b.empty_state())

    def test_revised_report_preserves_original_receipts_and_public_version_until_approved(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = example_issue()
            b.stage_issue(root, old)
            old_digest = b.issue_digest(old)
            b.promote_issue(root, old["date"], old_digest)
            state = b.load_state(root)
            parts = b.delivery_parts(old)
            for part in range(len(parts)):
                state = b.record_receipt(old, state, old_digest, part, len(parts))
            b.save_state(root, state)
            old_receipt = copy.deepcopy(state["receipts"][old["date"]])
            revised = copy.deepcopy(old)
            revised.update(revision=2, supersedes=old_digest, revision_note="Read full text and simplify community.",
                           headline="A revised single standout")
            with self.assertRaisesRegex(ValueError, "revise"):
                b.stage_issue(root, revised)
            with self.assertRaisesRegex(ValueError, "digest"):
                b.revise_issue(root, revised, "wrong")
            b.revise_issue(root, revised, old_digest)
            self.assertEqual(b.issue_digest(b.load_json(root / "reports" / (old["date"] + ".json"))), old_digest)
            self.assertEqual(b.load_state(root)["receipts"][old["date"]], old_receipt)
            self.assertEqual(b.delivery_key(revised), "2026-09-16:r2")
            self.assertNotIn(b.delivery_key(revised), b.load_state(root)["receipts"])
            archive = list((root / ".local" / "revisions" / old["date"]).glob("*.json"))
            self.assertEqual(len(archive), 1)
            self.assertEqual(b.issue_digest(b.load_json(archive[0])), old_digest)
            b.promote_issue(root, old["date"], b.issue_digest(revised))
            self.assertEqual(b.load_json(root / "reports" / (old["date"] + ".json"))["revision"], 2)
            state = b.load_state(root)
            for part in range(len(b.delivery_parts(revised))):
                state = b.record_receipt(revised, state, b.issue_digest(revised), part, len(b.delivery_parts(revised)))
            self.assertTrue(state["receipts"]["2026-09-16:r2"]["complete"])
            self.assertEqual(state["receipts"][old["date"]], old_receipt)
            self.assertIn("수정본 r2", b.report_text(revised))

    def test_revision_rejects_partial_delivery_wrong_revision_and_changed_public_base(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = example_issue()
            old["papers"][0]["method"] = "Long method. " * 3000
            b.stage_issue(root, old)
            digest = b.issue_digest(old)
            b.promote_issue(root, old["date"], digest)
            revised = copy.deepcopy(old)
            revised.update(revision=3, supersedes=digest, revision_note="Changes")
            with self.assertRaisesRegex(ValueError, "next revision"):
                b.revise_issue(root, revised, digest)
            revised["revision"] = 2
            state = b.record_receipt(old, b.load_state(root), digest, 0, len(b.delivery_parts(old)))
            b.save_state(root, state)
            with self.assertRaisesRegex(ValueError, "partial delivery"):
                b.revise_issue(root, revised, digest)

    def test_revision_promotion_requires_the_unchanged_approved_public_base(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = example_issue()
            b.stage_issue(root, old)
            digest = b.issue_digest(old)
            b.promote_issue(root, old["date"], digest)
            revised = copy.deepcopy(old)
            revised.update(revision=2, supersedes=digest, revision_note="A deliberate correction",
                           headline="Revised headline")
            b.revise_issue(root, revised, digest)
            concurrent = copy.deepcopy(old)
            concurrent["headline"] = "A different public change"
            b.atomic_json(root / "reports" / (old["date"] + ".json"), concurrent)
            with self.assertRaisesRegex(ValueError, "Public base digest"):
                b.promote_issue(root, old["date"], b.issue_digest(revised))
            self.assertEqual(b.load_json(root / "reports" / (old["date"] + ".json")), concurrent)

    def test_delivered_legacy_issue_can_be_revised_without_erasing_legacy_receipts(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = example_issue()
            old["schema_version"] = 1
            old.pop("lead")
            old["papers"][0]["evidence"] = "abstract_only"
            old["discussions"][0].update(summary="Old summary", significance="Old explanation", caveat="Old caveat")
            digest = b.issue_digest(old)
            b.atomic_json(root / ".local" / "drafts" / (old["date"] + ".json"), old)
            b.atomic_json(root / "reports" / (old["date"] + ".json"), old)
            state = b.empty_state()
            for index in range(len(b.delivery_parts(old))):
                state = b.record_receipt(old, state, digest, index, len(b.delivery_parts(old)))
            b.save_state(root, state)
            revised = example_issue()
            revised.update(revision=2, supersedes=digest, revision_note="Full-text rewrite")
            b.revise_issue(root, revised, digest)
            self.assertTrue(b.load_state(root)["receipts"][old["date"]]["complete"])
            self.assertEqual(b.load_draft(root, old["date"])["schema_version"], 2)
            self.assertEqual(b.load_json(root / "reports" / (old["date"] + ".json"))["schema_version"], 1)

    def test_v2_accepts_twelve_unique_community_links_and_rejects_a_thirteenth(self):
        b = self.api()
        issue = example_issue()
        source = issue["discussions"][0]
        issue["discussions"] = [
            {**source, "url": "https://example.org/story/" + str(index)}
            for index in range(12)
        ]
        b.validate_issue(issue, b.empty_state())
        issue["discussions"].append({**source, "url": "https://example.org/story/12"})
        with self.assertRaisesRegex(ValueError, "item limit"):
            b.validate_issue(issue, b.empty_state())

    def test_github_summary_keeps_all_ten_ranks_and_only_three_featured_items(self):
        b = self.api()
        issue = example_issue()
        sample = issue["repositories"][0]
        issue["repositories"] = [
            {**sample, "repository": "fixture/repo-" + str(i),
             "url": "https://github.com/fixture/repo-" + str(i), "rank": i}
            for i in range(1, 11)
        ]
        issue["github_snapshot"]["entries"] = [
            {"repository": r["repository"], "rank": r["rank"], "weekly_stars": 1000 + r["rank"]}
            for r in issue["repositories"]
        ]
        issue["github_featured"] = ["fixture/repo-5", "fixture/repo-9", "fixture/repo-4"]
        b.validate_issue(issue, b.empty_state())
        html = b.render_issue(issue).split('<section id="github">')[1].split("</section>")[0]
        self.assertIn('class="github-table"', html)
        self.assertEqual(html.count('class="repo-overview-row"'), 10)
        self.assertEqual(html.count('class="article-item repo-feature"'), 3)
        self.assertIn('class="repo-overflow"', html)
        self.assertIn("1,005", html)
        for r in issue["repositories"]:
            self.assertEqual(html.count('id="' + b.item_anchor("github", r) + '"'), 1)
        issue["github_featured"].append("fixture/repo-1")
        with self.assertRaisesRegex(ValueError, "featured"):
            b.validate_issue(issue, b.empty_state())

    def test_github_snapshot_only_rows_do_not_reinvent_old_descriptions(self):
        b = self.api()
        issue = example_issue()
        issue["github_snapshot"]["entries"].append({"repository": "fixture/old", "rank": 2, "weekly_stars": None})
        html = b.render_issue(issue)
        self.assertIn("fixture/old", html)
        self.assertIn("이번 호 상세 제외", html)
        issue["github_featured"] = ["fixture/old"]
        with self.assertRaisesRegex(ValueError, "featured"):
            b.validate_issue(issue, b.empty_state())

    def test_teams_digest_is_one_formatted_short_message_with_deployed_links(self):
        b = self.api()
        issue = example_issue()
        issue["teams"] = {
            "spotlight": ["A concise technical result.", "Trigger rate is not task success."],
            "highlights": [
                {"section": "github", "url": issue["repositories"][0]["url"], "text": "Context management"},
                {"section": "cncf", "url": issue["cncf"][0]["url"], "text": "Runtime update"},
            ],
        }
        b.validate_issue(issue, b.empty_state())
        message = b.teams_digest_html(issue, published=True)
        self.assertIn("<strong>Technical Spotlight</strong>", message)
        self.assertIn("<p>A concise technical result.</p>", message)
        self.assertEqual(message.count("<li>"), 2)
        self.assertIn("https://hellices.github.io/daily-tech-brief/daily/2026-09-16/", message)
        self.assertNotIn(issue["papers"][0]["method"], message)
        self.assertNotIn(issue["repositories"][0]["use_case"], message)
        self.assertLess(len(message.encode("utf-8")), 8000)
        unpublished = b.teams_digest_html(issue, published=False)
        self.assertNotIn("/daily/2026-09-16/", unpublished)
        self.assertIn("상세 보고서 게시 승인 대기", unpublished)
        issue["teams"]["spotlight"][0] = "<script>unsafe</script>"
        self.assertNotIn("<script>", b.teams_digest_html(issue, published=True))

    def test_teams_highlights_reject_unlinked_items_and_oversized_copy(self):
        b = self.api()
        issue = example_issue()
        issue["teams"] = {"spotlight": ["A short result."],
                          "highlights": [{"section": "papers", "url": "https://example.org/missing", "text": "Missing"}]}
        with self.assertRaisesRegex(ValueError, "highlight"):
            b.validate_issue(issue, b.empty_state())
        issue["teams"]["highlights"] = []
        issue["teams"]["spotlight"] = ["x" * 501]
        with self.assertRaisesRegex(ValueError, "spotlight"):
            b.validate_issue(issue, b.empty_state())

    def test_compact_receipts_do_not_reuse_full_report_receipts(self):
        b = self.api()
        issue = example_issue()
        state = b.empty_state()
        for index in range(len(b.delivery_parts(issue))):
            state = b.record_receipt(issue, state, b.issue_digest(issue), index, len(b.delivery_parts(issue)))
        message = b.teams_digest_html(issue, published=False)
        payload_digest = b.text_digest(message)
        updated = b.record_digest_receipt(issue, state, payload_digest, message, "teams-message-123", "preview")
        self.assertTrue(updated["receipts"][issue["date"]]["complete"])
        key = b.delivery_key(issue) + ":digest:preview"
        self.assertEqual(updated["digest_receipts"][key]["message_id"], "teams-message-123")
        self.assertEqual(b.record_digest_receipt(issue, updated, payload_digest, message, "teams-message-123", "preview"), updated)
        with self.assertRaisesRegex(ValueError, "digest"):
            b.record_digest_receipt(issue, state, "wrong", message, "teams-message-123", "preview")
        with self.assertRaisesRegex(ValueError, "message"):
            b.record_digest_receipt(issue, state, payload_digest, message, "", "preview")

    def test_digest_links_require_confirmed_current_publication_and_are_idempotent(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = example_issue()
            b.stage_issue(root, issue)
            preview = b.digest_payload(root, issue["date"])
            self.assertEqual(preview["mode"], "preview")
            self.assertEqual(preview["content_type"], "html")
            with self.assertRaisesRegex(ValueError, "publication"):
                b.digest_payload(root, issue["date"], "published")
            b.promote_issue(root, issue["date"], b.issue_digest(issue))
            self.assertEqual(b.digest_payload(root, issue["date"])["mode"], "preview")
            b.record_publication(root, issue["date"], b.issue_digest(issue))
            published = b.digest_payload(root, issue["date"])
            self.assertEqual(published["mode"], "published")
            state = b.record_digest_receipt(issue, b.load_state(root), published["message_digest"],
                                            published["message"], "sent-123", "published")
            b.save_state(root, state)
            self.assertTrue(b.digest_payload(root, issue["date"])["already_sent"])
            self.assertIsNone(b.digest_payload(root, issue["date"])["message"])
            changed = copy.deepcopy(issue)
            changed["summary"][0] = "Changed after the short message was sent"
            with self.assertRaisesRegex(ValueError, "digest delivery"):
                b.stage_issue(root, changed)


if __name__ == "__main__":
    unittest.main()
