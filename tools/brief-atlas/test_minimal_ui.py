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


class MinimalUITests(unittest.TestCase):
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

    def test_empty_chart_cell_palette_meets_text_contrast(self):
        css = (ROOT / "style.css").read_text()
        rules = {}
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            declarations = {name: value.strip() for name, value in re.findall(r"([\w-]+)\s*:\s*([^;{}]+)", body)}
            for selector in selectors.split(","):
                rules.setdefault(selector.strip(), {}).update(declarations)

        def luminance(value):
            value = re.sub(r"var\((--[\w-]+)\)", lambda match: rules[":root"][match.group(1)], value)
            self.assertRegex(value, r"^#[0-9a-fA-F]{6}$")
            channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
            return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for selector in (".zero-cell", ".self-cell", "#heatmap .no-data"):
            with self.subTest(selector=selector):
                self.assertIn(selector, rules)
                foreground = luminance(rules[selector]["color"])
                background = luminance(rules[selector]["background"])
                contrast = (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05)
                self.assertGreaterEqual(contrast, 4.5)


if __name__ == "__main__":
    unittest.main()
