import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class DiagramTests(unittest.TestCase):
    def api(self):
        path = ROOT / "diagram_reader.py"
        self.assertTrue(path.exists(), "SVG integration is not implemented")
        spec = importlib.util.spec_from_file_location("diagram_reader", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_unselected_diagrams_are_not_attached_to_a_report(self):
        b = self.api()
        self.assertIsNone(b.diagram_for("https://arxiv.org/abs/2609.15982"))
        self.assertIsNone(b.diagram_for("https://arxiv.org/abs/2609.00001"))

    def test_only_explicit_catalog_entries_provide_diagrams(self):
        b = self.api()
        with tempfile.TemporaryDirectory() as folder:
            b.ROOT = Path(folder)
            directory = b.ROOT / "diagrams"
            directory.mkdir()
            descriptor = {"lead_url": "https://example.org/paper", "file": "example.svg",
                          "title": "Test diagram", "caption": "Only a test fixture",
                          "sources": ["https://example.org/paper"]}
            (directory / "catalog.json").write_text(json.dumps([descriptor]), encoding="utf-8")
            svg = '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc"><title id="title">Test</title><desc id="desc">Test flow</desc><rect width="20" height="20"/></svg>'
            path = directory / "example.svg"
            path.write_text(svg, encoding="utf-8")
            self.assertEqual(b.diagram_for("https://example.org/paper"), descriptor)
            self.assertIsNone(b.diagram_for("https://example.org/another-paper"))
            self.assertEqual(ET.fromstring(b.validated_svg(path)).attrib["role"], "img")

    def test_svg_validation_rejects_scripts_external_references_and_active_content(self):
        b = self.api()
        for markup in (
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.org/tracker.png"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="alert(1)"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://example.org/a)"/></svg>',
        ):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "bad.svg"
                path.write_text(markup, encoding="utf-8")
                with self.assertRaises(ValueError):
                    b.validated_svg(path)


if __name__ == "__main__":
    unittest.main()
