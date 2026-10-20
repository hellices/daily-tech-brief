from html.parser import HTMLParser
from pathlib import Path
import unittest
import briefing


class HeaderLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("data-site-link"):
            self.links[attrs["data-site-link"]] = attrs


class SiteChromeTests(unittest.TestCase):
    def test_header_is_shared_with_visible_bidirectional_links(self):
        self.assertTrue(callable(getattr(briefing, "render_site_header", None)))
        for base, active in (("./", "archive"), ("../../", ""), ("../", "insights")):
            header = briefing.render_site_header(base, "<nav>fixture</nav>", active)
            links = HeaderLinks(header).links
            self.assertEqual(links["insights"]["href"], base + "insights/index.html")
            self.assertEqual(links["archive"]["href"], base + "index.html#date-archive")
            self.assertEqual(links["insights"].get("aria-current"), "page" if active == "insights" else None)
            self.assertIn('class="site-brand-mark"', header)
            self.assertIn('id="header-search"', header)
            self.assertNotIn("@@", header)

    def test_both_templates_reference_shared_theme_and_header(self):
        root = Path(briefing.__file__).parent
        for relative in ("template.html", "tools/brief-atlas/template.html"):
            template = (root / relative).read_text()
            for slot in ("@@SITE_STYLE@@", "@@SITE_THEME@@", "@@SITE_HEADER@@"):
                self.assertEqual(template.count(slot), 1)


if __name__ == "__main__":
    unittest.main()
