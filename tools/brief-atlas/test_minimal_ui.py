from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parent


class MinimalUITests(unittest.TestCase):
    def test_no_editorial_or_pipeline_sections(self):
        template = (ROOT / "template.html").read_text()
        for name in ("hero", "observations", "pipeline-strip", "methodology", "build-artifacts", "detail-story"):
            self.assertNotRegex(template, r'(?:id|class)="' + name + r'(?:[" ])')

    def test_no_generated_guidance_in_page_copy(self):
        content = (ROOT / "template.html").read_text() + (ROOT / "ui.js").read_text()
        for phrase in ("MODEL CALLS", "STATIC GRAPH", "MATERIALIZED", "반복 포착", "다음 질문",
                       "해 보세요", "해보세요", "같은 입력", "준비할지", "자동 추출된", "포착</b>"):
            self.assertNotIn(phrase, content)

    def test_existing_visual_exploration_controls_remain(self):
        template = (ROOT / "template.html").read_text()
        for name in ("graph", "heatmap", "kind", "span", "as-of", "tag", "node-search",
                     "evidence-list", "evidence-search", "minimum", "cross-kind", "reset"):
            self.assertIn('id="' + name + '"', template)

    def test_all_direct_dom_references_have_targets(self):
        template = (ROOT / "template.html").read_text()
        javascript = (ROOT / "ui.js").read_text()
        ids = set(re.findall(r'id="([^"]+)"', template))
        for name in re.findall(r"\$\('([^']+)'\)", javascript):
            self.assertIn(name, ids, "Orphaned DOM reference: " + name)


if __name__ == "__main__":
    unittest.main()
