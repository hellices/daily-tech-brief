import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("grouping.py")
G = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location("grouping", PATH)
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)

TAGS = [
    {"id": "memory", "label": "메모리", "aliases": []},
    {"id": "agent", "label": "에이전트", "aliases": ["agents"]},
    {"id": "security", "label": "보안", "aliases": []},
]


def article(key, title, topics, tags, summary="", day="2026-10-18", identity=None):
    return (
        {"id": key, "identity": identity or key, "date": day, "title": title,
         "tags": tags, "section": "papers"},
        {"topics": topics, "summary": summary}
    )


def build(articles):
    if G is None:
        raise AssertionError("Article grouping has not been implemented")
    return G.build_article_groups([x[0] for x in articles], [x[1] for x in articles], TAGS)


class GroupingTests(unittest.TestCase):
    def test_specific_shared_language_connects_articles_with_provenance(self):
        rows = [
            article("a", "Procedural Memory for Persistent Assistants",
                    ["procedural memory", "persistent assistants"], ["agent", "memory"]),
            article("b", "Evaluating Procedural Memory in Persistent Assistants",
                    ["procedural memory", "persistent assistants"], ["memory"]),
            article("c", "Network Resource Authorization for Sandboxes",
                    ["resource authorization"], ["security"]),
        ]
        result = build(rows)
        self.assertEqual(len(result["groups"]), 1)
        group = result["groups"][0]
        self.assertEqual(group["documents"], [0, 1])
        self.assertEqual(group["article_count"], 2)
        self.assertIn("procedural memory", group["terms"])
        self.assertEqual(group["links"][0]["source"], 0)
        self.assertEqual(group["links"][0]["target"], 1)
        self.assertGreater(group["links"][0]["score"], 0)
        self.assertIn("procedural memory", group["links"][0]["shared_terms"])
        self.assertEqual(result["ungrouped_documents"], [2])

    def test_shared_generic_tags_alone_do_not_connect_different_problems(self):
        result = build([
            article("a", "Procedural Memory for Persistent Assistants", ["procedural memory"], ["agent"]),
            article("b", "Quantized Tensor Kernels for Mobile Devices", ["quantized kernels"], ["agent"]),
        ])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["ungrouped_documents"], [0, 1])

    def test_candidate_gate_requires_shared_editorial_context(self):
        result = build([
            article("a", "Structured State Routing for Autonomous Tasks", ["structured state routing"], ["memory"]),
            article("b", "Structured State Routing for Autonomous Tasks", ["structured state routing"], ["security"]),
        ])
        self.assertEqual(result["groups"], [])

    def test_republished_source_is_not_independent_support(self):
        result = build([
            article("a", "Procedural Memory for Assistants", ["procedural memory"], ["memory"], identity="same"),
            article("b", "Procedural Memory for Assistants", ["procedural memory"], ["memory"], day="2026-10-19", identity="same"),
        ])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["unique_articles"], 1)

    def test_republication_keeps_all_original_occurrences_without_inflating_group_size(self):
        rows = [
            article("a", "Procedural Memory for Persistent Assistants", ["procedural memory"], ["memory"]),
            article("b", "Learning Procedural Memory for Persistent Assistants", ["procedural memory"], ["memory"]),
            article("repeat", "Procedural Memory for Persistent Assistants", ["procedural memory"], ["memory"],
                    day="2026-10-19", identity="a"),
        ]
        group = build(rows)["groups"][0]
        self.assertEqual(group["article_count"], 2)
        self.assertEqual(group["documents"], [0, 1, 2])
        self.assertEqual(len(group["links"]), 1)

    def test_complete_link_grouping_does_not_chain_unrelated_endpoints(self):
        self.assertIsNotNone(G)
        pairs = [
            {"source": 0, "target": 1, "score": .8},
            {"source": 1, "target": 2, "score": .7},
        ]
        groups = G.cluster_pairs(3, pairs)
        self.assertEqual(groups, [[0, 1]])

    def test_group_output_is_deterministic_and_has_no_input_mutation(self):
        import copy
        rows = [
            article("a", "Temporal State Tracking in Agent Memory", ["temporal state tracking"], ["memory"]),
            article("b", "Improving Temporal State Tracking in Agent Memory", ["temporal state tracking"], ["memory"]),
        ]
        original = copy.deepcopy(rows)
        self.assertEqual(build(rows), build(copy.deepcopy(rows)))
        self.assertEqual(rows, original)

    def test_single_common_word_does_not_create_a_reading_group(self):
        result = build([
            article("a", "Forecasting Retrieval Failures", [], ["agent"]),
            article("b", "Forecasting Token Costs", [], ["agent"]),
        ])
        self.assertEqual(result["groups"], [])

    def test_summary_boilerplate_cannot_promote_one_shared_product_word_into_a_group(self):
        summary = "Install Helm integration configuration using portable deployment templates"
        result = build([
            article("a", "Helm Version Update", ["Helm"], ["security"], summary),
            article("b", "Dashboard Access Controls", ["Helm"], ["security"], summary),
        ])
        self.assertEqual(result["groups"], [])

    def test_misaligned_evidence_fails_explicitly(self):
        self.assertIsNotNone(G)
        with self.assertRaises(ValueError):
            G.build_article_groups([{"identity": "x"}], [], TAGS)


if __name__ == "__main__":
    unittest.main()
