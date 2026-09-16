"""Read reviewed, source-grounded SVG assets without executable content."""

import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
ALLOWED_TAGS = {"svg", "title", "desc", "defs", "marker", "path", "rect", "line", "polyline", "polygon", "circle", "g", "text", "tspan"}


def diagram_for(lead_url):
    catalog = json.loads((ROOT / "diagrams/catalog.json").read_text(encoding="utf-8"))
    matches = [entry for entry in catalog if entry["lead_url"] == lead_url]
    if len(matches) > 1:
        raise ValueError("Multiple diagrams registered for one lead")
    if not matches:
        return None
    entry = matches[0]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.svg", entry["file"]):
        raise ValueError("Diagram file must be a local SVG basename")
    for source in entry["sources"]:
        parsed = urlsplit(source)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("Diagram sources must use credential-free HTTPS")
    return entry


def validated_svg(path):
    markup = Path(path).read_text(encoding="utf-8")
    if "<!DOCTYPE" in markup.upper() or "<!ENTITY" in markup.upper():
        raise ValueError("SVG declarations are not allowed")
    root = ET.fromstring(markup)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Expected SVG root")
    for element in root.iter():
        if element.tag.split("}")[-1] not in ALLOWED_TAGS:
            raise ValueError("SVG contains unsupported active elements")
        for attribute, value in element.attrib.items():
            name = attribute.split("}")[-1].lower()
            if name.startswith("on") or name in ("href", "style", "src"):
                raise ValueError("SVG contains active or external attributes")
            for reference in re.findall(r"url\((.*?)\)", value, re.I):
                if not re.fullmatch(r"#[a-zA-Z0-9_-]+", reference.strip()):
                    raise ValueError("SVG references must stay within the diagram")
    return markup
