"""Build static graph assets from the checked-out approved reports.

From the repository root:
    npm ci --prefix tools/brief-atlas --ignore-scripts
    python3 briefing.py build
    python3 tools/brief-atlas/build.py

The graph build requires no model, embedding service, or network access.
"""
import argparse
from html import escape
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from briefing import canonical_url, item_anchor, render_navigation, render_site_header
from atlas import build_graph, period_rows
from grouping import build_article_groups

COLLECTIONS = {"github": "repositories", "papers": "papers", "community": "discussions", "cncf": "cncf"}


def snapshot(issues, tags):
    known = {tag["id"] for tag in tags}
    result = {"version": 1, "repository": os.environ.get("GITHUB_REPOSITORY", "hellices/daily-tech-brief"),
              "tags": tags, "reports": [], "items": []}
    for issue in sorted(issues, key=lambda row: row["date"]):
        day = issue["date"]
        result["reports"].append({
            "date": day, "coverage": {section: value["status"] for section, value in issue["coverage"].items()}
        })
        for section, collection in COLLECTIONS.items():
            for item in issue[collection]:
                item_tags = item.get("tags", [])
                if not set(item_tags).issubset(known):
                    raise ValueError("Unknown report tags: " + day)
                anchor = item_anchor(section, item)
                fields = ("summary", "abstract_summary", "why_now", "use_case", "caution",
                          "method", "findings", "limitations", "practical_value", "impact",
                          "significance", "caveat")
                result["items"].append({
                    "id": day + ":" + anchor, "identity": anchor,
                    "date": day, "section": section,
                    "title": item.get("title", item.get("repository", "")),
                    "summary": item.get("abstract_summary", item.get("summary", "")),
                    "body": "\n".join(item[field] for field in fields if item.get(field)),
                    "topics": item.get("topics", []),
                    "application": item.get("practical_value", item.get("use_case", item.get("impact", ""))),
                    "limitations": item.get("limitations", item.get("caution", item.get("caveat", ""))),
                    "tags": sorted(set(item_tags)), "url": canonical_url(item["url"]),
                    "href": "../daily/" + day + "/index.html#" + anchor
                })
    if len({item["id"] for item in result["items"]}) != len(result["items"]):
        raise ValueError("Duplicate date/section/item ID")
    return result


def load_reports(reports, taxonomy, revision="local-input"):
    issues = []
    for path in sorted(reports.glob("*.json")):
        issue = json.loads(path.read_text(encoding="utf-8"))
        if path.stem != issue["date"]:
            raise ValueError("Report filename/date mismatch: " + str(path))
        issues.append(issue)
    if not issues:
        raise ValueError("No approved report files in " + str(reports))
    source = snapshot(issues, json.loads(taxonomy.read_text(encoding="utf-8"))["tags"])
    source["revision"] = revision
    return source


def static_overview(data):
    meta = data["meta"]
    parts = [f'<h1>탐색</h1><p>{meta["from"]} — {meta["to"]} · '
             f'{meta["report_count"]}개 보고서 · {meta["occurrences"]}개 게재 항목 · '
             f'{len(data["nodes"])}개 노드 · {len(data["links"])}개 연결</p>']
    parts.append("<h2>글 묶음</h2><ul>")
    for group in sorted(data["article_groups"]["groups"], key=lambda g: (g["last"], g["id"]), reverse=True)[:20]:
        parts.append('<li><a href="./index.html#group=' + group["id"] + '">' + escape(group["label"]) +
                     f'</a> · {group["article_count"]}건</li>')
    parts.append("</ul><h2>최근 소식</h2><ul>")
    for item in sorted(data["items"], key=lambda item: (item["date"], item["id"]), reverse=True)[:20]:
        parts.append('<li><a href="' + escape(item["href"], quote=True) + '">' +
                     escape(item["title"]) + "</a> · " + item["date"] + "</li>")
    parts.append("</ul>")
    return "".join(parts)


def build(source=None, output=None):
    if source is None:
        source = load_reports(REPO_ROOT / "reports", REPO_ROOT / "tags.json",
                              os.environ.get("GITHUB_SHA", "local-input"))
    output = output or REPO_ROOT / "site" / "insights"
    graph = build_graph(source)
    details = [{key: item.get(key, [] if key == "topics" else "") for key in
                ("summary", "body", "topics", "application", "limitations")}
               for item in sorted(source["items"], key=lambda i: (i["date"], i["id"]))]
    groups = build_article_groups(graph["items"], details, graph["tags"])
    membership = [[] for _ in graph["items"]]
    for group in groups["groups"]:
        for index in group["documents"]:
            membership[index].append(group["id"])
    grouped_items = [{**item, "nodes": membership[i]} for i, item in enumerate(graph["items"])]
    groups["periods"] = {unit: period_rows(grouped_items, graph["reports"], unit) for unit in ("week", "month")}
    graph["article_groups"] = groups
    data = {**graph, "details": details}
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    bundle = ROOT / "node_modules" / "d3"
    if not (bundle / "dist" / "d3.min.js").is_file():
        raise ValueError("Missing D3: run npm ci --prefix tools/brief-atlas --ignore-scripts")
    replacements = {
        "@@DATA@@": encoded,
        "@@STYLE@@": (ROOT / "style.css").read_text(encoding="utf-8"),
        "@@SITE_STYLE@@": (REPO_ROOT / "site-theme.css").read_text(encoding="utf-8"),
        "@@SITE_THEME@@": (REPO_ROOT / "site-theme.js").read_text(encoding="utf-8"),
        "@@SITE_HEADER@@": render_site_header("../", render_navigation([], None, "../"), "insights"),
        "@@READER@@": (REPO_ROOT / "reader.js").read_text(encoding="utf-8"),
        "@@ANALYTICS@@": (ROOT / "analytics.js").read_text(encoding="utf-8"),
        "@@UI@@": (ROOT / "ui.js").read_text(encoding="utf-8"),
        "@@STATIC@@": static_overview(graph),
    }
    for token in replacements:
        if page.count(token) != 1:
            raise ValueError("Missing or duplicate template token: " + token)
    page = re.sub("|".join(re.escape(token) for token in replacements),
                  lambda match: replacements[match.group(0)], page)
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(page, encoding="utf-8")
    for filename, content in (("graph.json", graph), ("evidence.json", details), ("groups.json", groups)):
        (output / filename).write_text(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    (output / "overview.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>탐색 · Daily Tech Brief</title><body>' + static_overview(graph) + '</body></html>', encoding="utf-8")
    (output / "D3-LICENSE.txt").write_text((bundle / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    print("Built", output, "with", len(graph["nodes"]), "nodes,", len(graph["links"]), "links")
    return graph


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=REPO_ROOT / "reports")
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "site" / "insights")
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA", "local-input"))
    args = parser.parse_args()
    build(load_reports(args.reports, args.taxonomy or args.reports.parent / "tags.json", args.revision), args.output)
