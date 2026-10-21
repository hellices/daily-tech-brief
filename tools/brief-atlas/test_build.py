import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
with patch("socket.socket", side_effect=AssertionError("Network call during build import")):
    import build
    import briefing


class BuildTests(unittest.TestCase):
    def fixture(self, root):
        reports = root / "reports"
        reports.mkdir()
        issue = {"date": "2026-10-18", "repositories": [], "papers": [], "cncf": [], "discussions": [],
                 "coverage": {s: {"status": "ok"} for s in build.COLLECTIONS}}
        issue["papers"] = [{"id": "arxiv:2610.12345", "title": "QUARTZ: Adaptive State Routing",
                            "url": "https://arxiv.org/abs/2610.12345", "topics": ["quartz state routing"],
                            "tags": ["agent"], "abstract_summary": "Synthetic pipeline fixture, not published data."}]
        (reports / "2026-10-18.json").write_text(json.dumps(issue))
        (root / "tags.json").write_text(json.dumps({"tags": [{"id": "agent", "label": "Agent", "aliases": []}]}))
        return reports, issue

    def test_url_identity_uses_existing_site_canonicalization(self):
        self.assertEqual(build.canonical_url("https://example.org/a/?id=1&utm_source=x#top"), "https://example.org/a?id=1")

    def test_local_reports_build_requires_no_network_and_outputs_graph_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, _ = self.fixture(root)
            with patch("socket.socket", side_effect=AssertionError("Unexpected network")):
                source = build.load_reports(reports, root / "tags.json", revision="fixture")
                build.build(source, root / "site" / "insights")
            output = root / "site" / "insights"
            graph = json.loads((output / "graph.json").read_text())
            self.assertEqual(graph["meta"]["model_calls"], 0)
            self.assertTrue(any(n["key"] == "quartz state routing" for n in graph["nodes"]))
            self.assertTrue((output / "evidence.json").exists())
            self.assertTrue((output / "overview.html").exists())
            self.assertNotIn("@@DATA@@", (output / "index.html").read_text())

    def test_pipeline_updates_on_new_report_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, issue = self.fixture(root)
            source = build.load_reports(reports, root / "tags.json", revision="fixture")
            build.build(source, root / "out")
            first = {str(p.relative_to(root / "out")): p.read_bytes()
                     for p in (root / "out").rglob("*") if p.is_file()}
            self.assertEqual(set(first), {"graph.json", "groups.json", "evidence.json", "index.html", "overview.html", "D3-LICENSE.txt"})
            build.build(source, root / "out")
            second = {str(p.relative_to(root / "out")): p.read_bytes()
                      for p in (root / "out").rglob("*") if p.is_file()}
            self.assertEqual(first, second)
            next_issue = copy.deepcopy(issue)
            next_issue["date"] = "2026-10-19"
            next_issue["papers"][0]["id"] = "arxiv:2610.12346"
            next_issue["papers"][0]["url"] = "https://arxiv.org/abs/2610.12346"
            next_issue["papers"][0]["topics"] = ["opal memory scheduling"]
            (reports / "2026-10-19.json").write_text(json.dumps(next_issue))
            build.build(build.load_reports(reports, root / "tags.json", revision="fixture"), root / "out")
            graph = json.loads((root / "out" / "graph.json").read_text())
            self.assertEqual(graph["meta"]["report_count"], 2)
            self.assertTrue(any(n["key"] == "opal memory scheduling" for n in graph["nodes"]))
            self.assertNotEqual(hashlib.sha256(first["graph.json"]).hexdigest(), hashlib.sha256((root / "out" / "graph.json").read_bytes()).hexdigest())
            for name in ("graph.json", "groups.json", "evidence.json", "index.html", "overview.html"):
                self.assertNotEqual(first[name], (root / "out" / name).read_bytes(), name)
            evidence = json.loads((root / "out" / "evidence.json").read_text())
            self.assertEqual(len(evidence), 2)
            self.assertEqual(evidence[1]["topics"], ["opal memory scheduling"])
            page = (root / "out" / "index.html").read_text()
            embedded = re.search(r'<script id="snapshot" type="application/json">(.*?)</script>', page, re.S)
            self.assertIsNotNone(embedded)
            snapshot = json.loads(embedded.group(1))
            self.assertEqual(snapshot["meta"]["report_count"], 2)
            self.assertEqual(snapshot["items"][-1]["date"], "2026-10-19")
            self.assertEqual(snapshot["nodes"], graph["nodes"])
            self.assertEqual(snapshot["details"], evidence)
            groups = json.loads((root / "out" / "groups.json").read_text())
            self.assertEqual(snapshot["article_groups"], groups)
            self.assertEqual(groups["unique_articles"], 2)
            overview = (root / "out" / "overview.html").read_text()
            expected_href = "../daily/2026-10-19/index.html#" + briefing.item_anchor("papers", next_issue["papers"][0])
            self.assertRegex(overview, r'<a\b[^>]*\bhref=["\']' + re.escape(expected_href) + r'["\']')
            self.assertIn("2개 보고서", overview)
            self.assertIn("2026-10-19", overview)
            self.assertEqual(first["D3-LICENSE.txt"], (root / "out" / "D3-LICENSE.txt").read_bytes())

    def test_no_manually_selected_research_catalog_is_required(self):
        self.assertFalse((Path(__file__).parent / "concepts.json").exists())

    def test_template_tokens_in_report_text_are_preserved_without_replacement(self):
        tokens = "@@DATA@@ @@STYLE@@ @@ANALYTICS@@ @@UI@@ @@D3@@ @@VIEWS@@ @@RENDERER@@ @@STATIC@@"
        text = tokens + " </script> </ScRiPt> </SCRIPT \t> <script>fixture</script>"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, issue = self.fixture(root)
            issue["papers"][0]["abstract_summary"] = text
            (reports / "2026-10-18.json").write_text(json.dumps(issue))
            source = build.load_reports(reports, root / "tags.json", revision="fixture")
            build.build(source, root / "out")
            page = (root / "out" / "index.html").read_text(encoding="utf-8")
            embedded = re.search(r'<script id="snapshot" type="application/json">(.*?)</script\s*>', page, re.S | re.I)
            self.assertIsNotNone(embedded)
            self.assertNotIn("<", embedded.group(1))
            data = json.loads(embedded.group(1))
            self.assertEqual(data["details"][0]["summary"], text)
            self.assertEqual(data["details"][0]["body"], text)
            evidence = json.loads((root / "out" / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence, data["details"])

    def test_original_template_rejects_missing_and_duplicate_tokens(self):
        read_text = Path.read_text
        template = (build.ROOT / "template.html").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, _ = self.fixture(root)
            source = build.load_reports(reports, root / "tags.json", revision="fixture")
            for token in re.findall(r"@@[A-Z_]+@@", template):
                for replacement in ("", token * 2):
                    def read(path, *args, **kwargs):
                        if path == build.ROOT / "template.html":
                            return template.replace(token, replacement)
                        return read_text(path, *args, **kwargs)

                    with self.subTest(token=token, replacement=replacement), patch.object(Path, "read_text", read):
                        with self.assertRaisesRegex(ValueError, "Missing or duplicate template token: " + token):
                            build.build(source, root / "out")
                        self.assertFalse((root / "out").exists())

    def test_uses_existing_item_anchors_and_relative_site_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, issue = self.fixture(root)
            issue["papers"][0]["id"] = "https://arxiv.org/abs/2610.12345v2"
            (reports / "2026-10-18.json").write_text(json.dumps(issue))
            source = build.load_reports(reports, root / "tags.json")
            expected = briefing.item_anchor("papers", issue["papers"][0])
            self.assertEqual(source["items"][0]["href"], "../daily/2026-10-18/index.html#" + expected)
            self.assertEqual(source["items"][0]["identity"], expected)


if __name__ == "__main__":
    unittest.main()
