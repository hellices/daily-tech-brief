import importlib.util
import json
import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).with_name("atlas.py")
ATLAS = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location("atlas", PATH)
    ATLAS = importlib.util.module_from_spec(spec)
    with patch("socket.socket", side_effect=AssertionError("Network call during import")):
        spec.loader.exec_module(ATLAS)

OFFLINE_PROGRAM = (
    "import json, sys\n"
    "from unittest.mock import patch\n"
    "source = json.loads(sys.stdin.buffer.read())\n"
    "with patch('socket.socket', side_effect=AssertionError('Network call during build')):\n"
    "    from atlas import build_graph\n"
    "    graph = build_graph(source)\n"
    "sys.stdout.buffer.write(json.dumps(graph, ensure_ascii=False, sort_keys=True).encode('utf-8'))\n"
)


def document(key, day, topics=None, title="A study", section="papers", url="https://example.org/a"):
    return {"id": day + ":" + section + ":" + key, "identity": section + ":" + key, "date": day,
            "section": section, "title": title, "topics": topics or [], "tags": ["memory"],
            "url": url, "href": "https://example.org/daily/" + day + "#" + key,
            "body": "Original explanatory text", "summary": "Original summary"}


def source(items):
    return {"revision": "test", "repository": "example/brief", "tags": [
        {"id": "memory", "label": "메모리", "aliases": ["memory"]},
        {"id": "kubernetes", "label": "Kubernetes", "aliases": ["k8s"]}],
        "items": items, "reports": [
            {"date": day, "coverage": {s: "ok" for s in ("github", "papers", "community", "cncf")}}
            for day in sorted({i["date"] for i in items})]}


class AtlasTests(unittest.TestCase):
    def graph(self, items):
        self.assertIsNotNone(ATLAS, "Missing deterministic graph builder")
        return ATLAS.build_graph(source(items))

    def test_new_phrases_are_discovered_without_a_catalog(self):
        g = self.graph([document("a", "2026-10-18", ["quartz state routing"])])
        self.assertIn("quartz state routing", [n["key"] for n in g["nodes"]])

    def test_generic_editorial_tags_are_context_not_graph_nodes(self):
        g = self.graph([document("a", "2026-10-18", ["benchmark"], title="Kubernetes memory")])
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["items"][0]["tags"], ["memory"])

    def test_names_and_projects_are_separate_from_multiword_expressions(self):
        g = self.graph([
            document("a", "2026-10-18", ["weak-to-strong escalation"], title="LEASH: Weak-to-Strong Escalation"),
            document("b", "2026-10-18", title="vendor/ProjectX", section="github", url="https://github.com/vendor/ProjectX")
        ])
        self.assertTrue(any(n["kind"] == "phrase" for n in g["nodes"]))
        self.assertTrue(any(n["kind"] == "name" and n["label"] == "LEASH" for n in g["nodes"]))
        self.assertTrue(any(n["kind"] == "project" and n["key"] == "vendor/projectx" for n in g["nodes"]))

    def test_non_repository_github_routes_do_not_create_projects(self):
        paths = ("login/oauth", "sponsors/example", "settings/billing", "marketplace/actions",
                 "notifications/threads", "sessions/verified-device", "features/actions",
                 "topics/machine-learning", "orgs/example", "users/example",
                 "advisories/GHSA-abcd-1234-abcd", "stars/example", "discussions/example")
        for route in paths:
            with self.subTest(route=route):
                graph = self.graph([document("a", "2026-10-18", url="https://github.com/" + route)])
                self.assertFalse(any(n["kind"] == "project" for n in graph["nodes"]))
                self.assertEqual(len(graph["items"]), 1)

    def test_supported_repository_routes_and_punctuation_are_preserved(self):
        for tail in ("", "/", "/releases", "/releases/latest", "/releases/tag/v1.0",
                     "/issues/42", "/pull/3", "/blob/main/src/a.py", "/tree/main",
                     "/commit/abcdef1", "/discussions/6", "/actions/runs/123"):
            with self.subTest(tail=tail):
                graph = self.graph([document("a", "2026-10-18", url="https://github.com/actions/my_repo.test" + tail)])
                projects = [n for n in graph["nodes"] if n["kind"] == "project"]
                self.assertEqual([n["key"] for n in projects], ["actions/my_repo.test"])

    def test_unsupported_or_malformed_repository_urls_are_not_guessed(self):
        urls = ("https://github.com/example/repo/unknown-route",
                "https://github.com/example/repo/issues/not-a-number",
                "https://github.com/example/repo/blob",
                "https://github.com/example/repo/commit/not-a-sha",
                "https://github.com//example/repo",
                "https://github.com/example/..",
                "https://github.com/exa_mple/repo",
                "https://github.com.evil.example/example/repo",
                "https://user:password@github.com/example/repo")
        for url in urls:
            with self.subTest(url=url):
                graph = self.graph([document("a", "2026-10-18", url=url)])
                self.assertFalse(any(n["kind"] == "project" for n in graph["nodes"]))

    def test_literal_phrases_can_connect_papers_to_other_sections(self):
        g = self.graph([
            document("a", "2026-10-17", ["procedural memory"]),
            document("b", "2026-10-18", title="Building procedural-memory systems", section="community")
        ])
        node = next(n for n in g["nodes"] if n["key"] == "procedural memory")
        self.assertEqual(node["unique_count"], 2)
        self.assertEqual(set(node["sections"]), {"papers", "community"})
        matches = g["items"][1]["matches"][node["id"]]
        self.assertEqual(matches[0]["field"], "title")

    def test_word_boundaries_do_not_match_unrelated_substrings(self):
        g = self.graph([
            document("a", "2026-10-17", ["procedural memory"]),
            document("b", "2026-10-18", title="Nonprocedural memory")
        ])
        node = next(n for n in g["nodes"] if n["key"] == "procedural memory")
        self.assertEqual(node["unique_count"], 1)

    def test_case_and_hyphens_merge_only_lexical_variants(self):
        g = self.graph([
            document("a", "2026-10-17", ["Context Compression", "context-compression"]),
            document("b", "2026-10-18", ["context compaction"])
        ])
        phrases = [n for n in g["nodes"] if n["kind"] == "phrase"]
        self.assertEqual(len(phrases), 2)
        self.assertEqual(next(n for n in phrases if n["key"] == "context compression")["occurrences"], 1)

    def test_edges_require_same_entry_and_keep_provenance(self):
        g = self.graph([
            document("a", "2026-10-17", ["memory admission", "bounded retrieval"]),
            document("b", "2026-10-17", ["semantic verification"])
        ])
        self.assertEqual(len(g["links"]), 1)
        self.assertEqual(g["links"][0]["documents"], [0])
        self.assertEqual(g["links"][0]["type"], "co-mentioned")

    def test_republished_entries_do_not_inflate_unique_document_count(self):
        g = self.graph([
            document("a", "2026-10-17", ["procedural memory"]),
            document("a", "2026-10-18", ["procedural memory"])
        ])
        n = g["nodes"][0]
        self.assertEqual(n["occurrences"], 2)
        self.assertEqual(n["unique_count"], 1)
        self.assertEqual(n["first"], "2026-10-17")
        self.assertEqual(n["last"], "2026-10-18")

    def test_rollups_are_generated_at_build_time(self):
        g = self.graph([
            document("a", "2026-10-05", ["procedural memory"]),
            document("b", "2026-10-12", ["procedural memory"])
        ])
        self.assertEqual([w["from"] for w in g["periods"]["week"]], ["2026-10-05", "2026-10-12"])
        self.assertEqual(g["periods"]["month"][0]["item_count"], 2)
        self.assertEqual(g["periods"]["month"][0]["node_counts"][g["nodes"][0]["id"]], 2)

    def test_missing_weeks_remain_explicit(self):
        g = self.graph([
            document("a", "2026-10-05", ["procedural memory"]),
            document("b", "2026-10-26", ["procedural memory"])
        ])
        self.assertEqual(len(g["periods"]["week"]), 4)
        self.assertEqual(g["periods"]["week"][1]["report_count"], 0)
        self.assertEqual(g["periods"]["week"][1]["item_count"], 0)

    def test_output_is_byte_reproducible_across_hash_seeds_with_network_disabled(self):
        self.assertIsNotNone(ATLAS, "Missing deterministic graph builder")
        data = source([
            document("a", "2026-10-17", ["new adaptive planning", "bounded retrieval"], title="QUARTZ"),
            document("b", "2026-10-18", ["bounded retrieval", "procedural memory"], title="ORBIT",
                     section="github", url="https://github.com/example/planner"),
            document("a", "2026-10-19", ["new adaptive planning"], title="QUARTZ")
        ])
        outputs = []
        for seed in ("1", "7", "123"):
            with self.subTest(seed=seed):
                result = subprocess.run(
                    [sys.executable, "-c", OFFLINE_PROGRAM], cwd=PATH.parent,
                    env={**os.environ, "PYTHONHASHSEED": seed},
                    input=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                    capture_output=True, timeout=15, check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
                outputs.append(result.stdout)
                self.assertEqual(outputs[0], result.stdout)
        graph = json.loads(outputs[0])
        self.assertGreater(len(graph["nodes"]), 1)
        self.assertTrue(graph["links"])

    def test_offline_guard_blocks_import_side_effects_and_copied_socket_aliases(self):
        modules = (
            "from socket import socket\nsocket()\ndef build_graph(source): return {}\n",
            "from socket import socket\ndef build_graph(source):\n    socket()\n    return {}\n",
        )
        for module in modules:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as temporary:
                Path(temporary, "atlas.py").write_text(module)
                result = subprocess.run(
                    [sys.executable, "-c", OFFLINE_PROGRAM], cwd=temporary,
                    input=b"{}", capture_output=True, timeout=15, check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Network call during build", result.stderr)

    def test_appending_a_report_updates_graph_without_changing_existing_ids(self):
        old = [document("a", "2026-10-17", ["procedural memory"])]
        before = self.graph(old)
        after = self.graph(old + [document("b", "2026-10-18", ["quartz state routing"])])
        self.assertEqual(before["nodes"][0]["id"], next(n["id"] for n in after["nodes"] if n["key"] == "procedural memory"))
        self.assertTrue(any(n["key"] == "quartz state routing" for n in after["nodes"]))

    def test_deleting_a_report_removes_orphaned_nodes_and_edges(self):
        old = [document("a", "2026-10-17", ["procedural memory"]),
               document("b", "2026-10-18", ["quartz state routing", "bounded retrieval"])]
        before = self.graph(old)
        self.assertEqual(len(before["links"]), 1)
        deleted = {n["id"] for n in before["nodes"] if n["key"] != "procedural memory"}
        rebuilt = self.graph(old[:1])
        self.assertFalse(any(n["key"] == "quartz state routing" for n in rebuilt["nodes"]))
        self.assertEqual(rebuilt["links"], [])
        self.assertFalse(any(n["id"] in deleted for n in rebuilt["nodes"]))

    def test_project_keys_preserve_punctuation_but_merge_case_variants(self):
        graph = self.graph([
            document("a", "2026-10-17", url="https://github.com/Owner/My-Repo"),
            document("b", "2026-10-18", url="https://github.com/owner/my_repo"),
            document("c", "2026-10-18", url="https://github.com/owner/my-repo")
        ])
        projects = {n["key"]: n for n in graph["nodes"] if n["kind"] == "project"}
        self.assertEqual(set(projects), {"owner/my-repo", "owner/my_repo"})
        self.assertNotEqual(projects["owner/my-repo"]["id"], projects["owner/my_repo"]["id"])
        self.assertEqual(projects["owner/my-repo"]["unique_count"], 2)
        self.assertEqual(projects["owner/my_repo"]["unique_count"], 1)

    def test_all_sections_and_unextracted_entries_remain_in_inventory(self):
        g = self.graph([document("a", "2026-10-18", section=s) for s in ("papers", "github", "community", "cncf")])
        self.assertEqual(len(g["items"]), 4)
        self.assertEqual(set(g["meta"]["sections"]), {"papers", "github", "community", "cncf"})

    def test_invalid_dates_are_not_silently_bucketed(self):
        self.assertIsNotNone(ATLAS, "Missing deterministic graph builder")
        with self.assertRaises(ValueError):
            ATLAS.build_graph(source([document("a", "2026-02-30", ["procedural memory"])]))

    def test_generic_acronyms_do_not_dominate_name_navigation(self):
        g = self.graph([document("a", "2026-10-18", title="AI ML CLI SDK APIs HN GN with OpenAI")])
        self.assertEqual([n["label"] for n in g["nodes"]], ["OpenAI"])

    def test_longest_phrase_avoids_artificial_parent_child_cooccurrence(self):
        g = self.graph([
            document("a", "2026-10-17", ["self-improvement"]),
            document("b", "2026-10-18", ["recursive self-improvement"])
        ])
        phrases = {n["key"]: n for n in g["nodes"] if n["kind"] == "phrase"}
        self.assertEqual(set(phrases), {"self improvement", "recursive self improvement"})
        for key, index in (("self improvement", 0), ("recursive self improvement", 1)):
            self.assertEqual(phrases[key]["unique_count"], 1)
            self.assertEqual(phrases[key]["documents"], [index])
            self.assertIn(phrases[key]["id"], g["items"][index]["nodes"])
        self.assertEqual(g["items"][1]["id"], "2026-10-18:papers:b")
        self.assertEqual(g["links"], [])


if __name__ == "__main__":
    unittest.main()
