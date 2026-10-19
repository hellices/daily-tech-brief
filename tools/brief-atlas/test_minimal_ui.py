from pathlib import Path
from html.parser import HTMLParser
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent


class SectionMarkers(HTMLParser):
    def __init__(self):
        super().__init__()
        self.markers = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.markers.add(attributes["id"])
        self.markers.update((attributes.get("class") or "").split())


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.excluded = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.excluded = tag
        elif tag in ("p", "div", "section", "li", "br"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == self.excluded:
            self.excluded = None
        if tag in ("p", "div", "section", "li"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self.excluded is None:
            self.parts.append(data)


class MinimalUITests(unittest.TestCase):
    def test_copy_guard_checks_rendered_markup_and_decoded_entities(self):
        for template in ("<p>다음 <span>질문</span></p>", "<p>다음&#32;질문</p>",
                         "<p>다음&nbsp;질문</p>", "<p>다음\n\t질문</p>"):
            with self.subTest(template=template), patch.object(
                Path, "read_text", side_effect=[template, ""]
            ):
                with self.assertRaises(AssertionError):
                    self.test_no_generated_guidance_in_page_copy()

    def test_section_guard_checks_every_class_token_and_quote_style(self):
        for html in ('<section class="panel hero">', "<div class='panel hero compact'>",
                     '<section class="panel' + chr(9) + 'hero">', "<aside id='observations'>"):
            with self.subTest(html=html), patch.object(Path, "read_text", return_value=html):
                with self.assertRaises(AssertionError):
                    self.test_no_editorial_or_pipeline_sections()

    def test_no_editorial_or_pipeline_sections(self):
        template = (ROOT / "template.html").read_text()
        parser = SectionMarkers()
        parser.feed(template)
        for name in ("hero", "observations", "pipeline-strip", "methodology", "build-artifacts", "detail-story"):
            self.assertNotIn(name, parser.markers)

    def test_no_generated_guidance_in_page_copy(self):
        parser = PageText()
        parser.feed((ROOT / "template.html").read_text())
        template_text = " ".join("".join(parser.parts).split())
        javascript = (ROOT / "ui.js").read_text()
        for phrase in ("MODEL CALLS", "STATIC GRAPH", "MATERIALIZED", "반복 포착", "다음 질문",
                       "해 보세요", "해보세요", "같은 입력", "준비할지", "자동 추출된", "포착</b>"):
            self.assertNotIn(phrase, template_text)
            self.assertNotIn(phrase, javascript)

    def test_existing_visual_exploration_controls_remain(self):
        template = (ROOT / "template.html").read_text()
        for name in ("graph", "heatmap", "kind", "span", "as-of", "tag", "node-search",
                     "evidence-list", "evidence-search", "minimum", "cross-kind", "reset"):
            self.assertIn('id="' + name + '"', template)

    def test_all_direct_dom_references_have_targets(self):
        template = (ROOT / "template.html").read_text()
        javascript = (ROOT / "ui.js").read_text()
        ids = set(re.findall(r'id="([^"]+)"', template))
        for _, name in re.findall(r"""\$\(\s*(['"])([^'"]+)\1\s*\)""", javascript):
            self.assertIn(name, ids, "Orphaned DOM reference: " + name)

    def test_dom_guard_rejects_missing_targets_with_either_quote_style(self):
        for reference in ("$('missing-target')", ' $("missing-target") ',
                          "$(\n 'missing-target' \t)", '$(\t"missing-target"\n)'):
            with self.subTest(reference=reference), patch.object(
                Path, "read_text", side_effect=['<div id="existing"></div>', reference]
            ):
                with self.assertRaisesRegex(AssertionError, "Orphaned DOM reference: missing-target"):
                    self.test_all_direct_dom_references_have_targets()

if __name__ == "__main__":
    unittest.main()
