"""Deterministic graph materialization. Standard library only; no network or model calls."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
from itertools import combinations
import json
import re
import unicodedata
from urllib.parse import urlsplit

SECTIONS = ("github", "papers", "community", "cncf")
COMMON_WORDS = frozenset(("A AN THE AND OR FOR WITH ON IN OF TO FROM HOW WHY WHAT WHEN IS ARE NOT NEW VS "
                          "AI ML API APIS CLI SDK HTTP HTTPS URL JSON HTML HN GN CD CI CPU GPU").split())
GITHUB_SITE_ROUTES = frozenset((
    "about account advisories apps codespaces collections contact copilot customer-stories dashboard "
    "discussions enterprise events explore features github-copilot issues join login logout marketplace new notifications "
    "organizations orgs pricing pulls readme resources search security sessions settings signup site "
    "solutions sponsors stars topics trending users"
).split())
GITHUB_REPOSITORY_PATH = re.compile(
    r"/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9_.-]{1,104})(?:/(.*))?"
)
GITHUB_REPOSITORY_RESOURCE = re.compile(
    r"(?:releases(?:/(?:latest|tag/.+))?"
    r"|issues(?:/[0-9]+)?|pull/[0-9]+(?:/(?:files|commits|checks))?"
    r"|discussions(?:/[0-9]+)?|blob/[^/]+/.+|tree/[^/]+(?:/.+)?"
    r"|commit/[a-fA-F0-9]{7,40}|commits(?:/.+)?|compare/.+"
    r"|actions(?:/runs/[0-9]+)?|security/advisories(?:/GHSA-[a-zA-Z0-9-]+)?"
    r"|wiki(?:/.+)?|branches|tags)"
)


def normalize(value):
    return re.sub(r"[\s\-\u2010-\u2015_]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def node_id(kind, key):
    return kind + "-" + hashlib.sha256((kind + ":" + key).encode("utf-8")).hexdigest()[:16]


def github_repository(value):
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    match = GITHUB_REPOSITORY_PATH.fullmatch(url.path)
    if not match:
        return None
    owner, repository, resource = match.groups()
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    if (owner.lower() in GITHUB_SITE_ROUTES or "--" in owner
            or repository in ("", ".", "..") or len(repository) > 100 or repository.lower().endswith(".git")):
        return None
    if resource and not GITHUB_REPOSITORY_RESOURCE.fullmatch(resource.rstrip("/")):
        return None
    return owner + "/" + repository


def next_period(start, unit):
    if unit == "week":
        return start + timedelta(days=7)
    return date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def period_rows(items, reports, unit):
    first, last = date.fromisoformat(reports[0]["date"]), date.fromisoformat(reports[-1]["date"])
    start = first - timedelta(days=first.weekday()) if unit == "week" else first.replace(day=1)
    rows = []
    while start <= last:
        end = min(next_period(start, unit) - timedelta(days=1), last)
        a, b = start.isoformat(), end.isoformat()
        current = [i for i in items if a <= i["date"] <= b]
        observed = [r for r in reports if a <= r["date"] <= b]
        node_documents = defaultdict(set)
        for item in current:
            for identifier in item["nodes"]:
                node_documents[identifier].add(item["identity"])
        rows.append({
            "from": a, "to": b, "report_count": len(observed), "expected_days": (end - start).days + 1,
            "item_count": len({i["identity"] for i in current}), "occurrences": len(current),
            "node_counts": {key: len(value) for key, value in sorted(node_documents.items())},
            "sections": {s: len({i["identity"] for i in current if i["section"] == s}) for s in SECTIONS},
            "partial_slots": sum(status != "ok" for r in observed for status in r["coverage"].values())
        })
        start = next_period(start, unit)
    return rows


def build_graph(source):
    reports = sorted(source["reports"], key=lambda r: r["date"])
    if not reports:
        raise ValueError("No reports to materialize")
    for report in reports:
        date.fromisoformat(report["date"])
    original = sorted(source["items"], key=lambda i: (i["date"], i["id"]))
    if len({i["id"] for i in original}) != len(original):
        raise ValueError("Duplicate source item ID")
    broad = {normalize(value) for tag in source["tags"] for value in [tag["id"], tag["label"], *tag.get("aliases", [])]}
    vocabulary = {}

    def register(kind, label):
        key = label.casefold() if kind == "project" else normalize(label)
        identifier = node_id(kind, key)
        if identifier not in vocabulary:
            vocabulary[identifier] = {"id": identifier, "kind": kind, "key": key, "labels": set()}
        vocabulary[identifier]["labels"].add(label.strip())
        return identifier

    # Structured keywords supply vocabulary, never a hand-maintained research-topic whitelist.
    for item in original:
        date.fromisoformat(item["date"])
        if item["section"] not in SECTIONS:
            raise ValueError("Unknown source section: " + item["section"])
        for topic in item.get("topics", []):
            key = normalize(topic)
            if 2 <= len(key.split()) <= 8 and len(key) <= 100 and key not in broad:
                register("phrase", topic)
    expressions = [(n["id"], re.compile(r"(?<!\w)" + re.escape(n["key"]) + r"(?!\w)"))
                   for n in vocabulary.values() if n["kind"] == "phrase"]
    items, documents = [], defaultdict(list)
    for index, item in enumerate(original):
        matches = defaultdict(list)
        for field, text in [("title", item["title"]), *[("topics", t) for t in item.get("topics", [])]]:
            normal = normalize(text)
            found = [(identifier, match.start(), match.end()) for identifier, pattern in expressions
                     for match in pattern.finditer(normal)]
            for identifier, start, end in found:
                if not any(other != identifier and a <= start and b >= end and b - a > end - start
                           for other, a, b in found):
                    hit = {"field": field, "text": text}
                    if hit not in matches[identifier]:
                        matches[identifier].append(hit)
        project = github_repository(item["url"])
        if project:
            matches[register("project", project)].append({"field": "url", "text": item["url"]})
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:[._/-][A-Za-z0-9]+)*\b", item["title"]):
            if "/" in token or not 2 <= len(token) <= 45 or normalize(token) in broad or token.upper() in COMMON_WORDS:
                continue
            if (re.search(r"[a-z][A-Z]", token) or re.search(r"[A-Za-z]\d", token)
                    or (token.isupper() and 2 <= len(token) <= 12)):
                identifier = register("name", token)
                hit = {"field": "title", "text": token}
                if hit not in matches[identifier]:
                    matches[identifier].append(hit)
        for identifier in matches:
            documents[identifier].append(index)
        items.append({key: item[key] for key in ("id", "identity", "date", "section", "title", "tags", "url", "href")})
        items[-1].update({"nodes": sorted(matches), "matches": dict(sorted(matches.items()))})
    nodes = []
    for identifier, indices in sorted(documents.items()):
        vocabulary_entry = vocabulary[identifier]
        rows = [items[i] for i in indices]
        daily = Counter((i["date"], i["section"]) for i in rows)
        nodes.append({key: vocabulary_entry[key] for key in ("id", "kind", "key")})
        nodes[-1].update({
            "label": sorted(vocabulary_entry["labels"], key=lambda s: (s.casefold(), s))[0],
            "documents": indices, "first": rows[0]["date"], "last": rows[-1]["date"],
            "occurrences": len(rows), "unique_count": len({i["identity"] for i in rows}),
            "sections": sorted({i["section"] for i in rows}),
            "daily": [{"date": day, "section": section, "count": count} for (day, section), count in sorted(daily.items())]
        })
    links = defaultdict(list)
    for index, item in enumerate(items):
        for a, b in combinations(item["nodes"], 2):
            links[(a, b)].append(index)
    digest = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "version": 3,
        "meta": {"repository": source.get("repository", ""), "revision": source.get("revision", ""),
                 "source_digest": digest, "model_calls": 0, "extractor": "literal-v1",
                 "from": reports[0]["date"], "to": reports[-1]["date"],
                 "report_count": len(reports), "occurrences": len(items),
                 "unique_items": len({i["identity"] for i in items}),
                 "matched_items": sum(bool(i["nodes"]) for i in items),
                 "sections": {s: sum(i["section"] == s for i in items) for s in SECTIONS},
                 "node_kinds": dict(Counter(n["kind"] for n in nodes)),
                 "link_count": len(links)},
        "reports": reports, "tags": sorted(source["tags"], key=lambda t: t["id"]),
        "items": items, "nodes": nodes,
        "links": [{"source": a, "target": b, "type": "co-mentioned", "documents": indices,
                   "first": items[indices[0]]["date"], "last": items[indices[-1]]["date"]}
                  for (a, b), indices in sorted(links.items())],
        "periods": {unit: period_rows(items, reports, unit) for unit in ("week", "month")}
    }
