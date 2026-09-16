#!/usr/bin/env python3
"""Validate, deliver, and render a source-grounded daily briefing."""

import argparse
import calendar
import copy
from datetime import date, datetime, timedelta
import hashlib
from html import escape
import json
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "issue-schema.json").read_text(encoding="utf-8"))
TAXONOMY = json.loads((ROOT / "tags.json").read_text(encoding="utf-8"))
TAGS = {tag["id"]: tag for tag in TAXONOMY["tags"]}
KST = ZoneInfo("Asia/Seoul")
SECTIONS = ("github", "papers", "community", "cncf")
ITEM_COLLECTIONS = {"github": "repositories", "papers": "papers", "community": "discussions", "cncf": "cncf"}
SECTION_LABELS = {"github": "GitHub", "papers": "AI 논문", "community": "커뮤니티", "cncf": "CNCF"}
MAX_PART_BYTES = 16000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), name + " must be nonempty text")
    return value


def tag_key(value):
    return re.sub(r"[\s_]+", "-", unicodedata.normalize("NFKC", text(value, "tag")).strip().casefold())


def normalize_tags(values):
    require(isinstance(values, list) and 1 <= len(values) <= 10, "Item tags must be a nonempty array")
    lookup = {}
    for identifier, tag in TAGS.items():
        for alias in [identifier, tag["label"], *tag["aliases"]]:
            key = tag_key(alias)
            require(key not in lookup or lookup[key] == identifier, "Ambiguous tag alias: " + alias)
            lookup[key] = identifier
    normalized = set()
    for value in values:
        key = tag_key(value)
        require(key in lookup, "Unknown tag: " + value + "; use tags.json")
        normalized.add(lookup[key])
    require(len(normalized) <= 5, "An item may have at most five canonical tags")
    return sorted(normalized)


def iso_day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "Invalid ISO date")
    return date.fromisoformat(value)


def aware_time(value):
    moment = datetime.fromisoformat(text(value, "timestamp").replace("Z", "+00:00"))
    require(moment.tzinfo is not None, "Timestamp must include a timezone")
    return moment


def safe_url(value):
    text(value, "source URL")
    require(not any(ord(char) < 33 for char in value), "Unsafe source URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username
            and not parsed.password, "Sources must use credential-free HTTPS URLs")
    return value


def canonical_url(value):
    parsed = urlsplit(safe_url(value))
    query = [(key, val) for key, val in parse_qsl(parsed.query)
             if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")]
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"),
                       urlencode(sorted(query)), ""))


def repository_id(value):
    text(value, "repository")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", value)
            and value.split("/")[1] not in (".", ".."), "Invalid owner/repository")
    return value.lower()


def canonical_paper_id(value):
    value = text(value, "paper ID").strip()
    if value.startswith("https://"):
        parsed = urlsplit(safe_url(value))
        if parsed.hostname in ("arxiv.org", "www.arxiv.org") and parsed.path.startswith(("/abs/", "/pdf/")):
            value = "arxiv:" + re.sub(r"\.pdf$", "", parsed.path.split("/", 2)[2])
        elif parsed.hostname in ("doi.org", "dx.doi.org"):
            value = "doi:" + parsed.path.lstrip("/")
        elif parsed.hostname == "openreview.net" and parse_qs(parsed.query).get("id"):
            value = "openreview:" + parse_qs(parsed.query)["id"][0]
        else:
            return "url:" + canonical_url(value)
    if value.lower().startswith("arxiv:"):
        identifier = re.sub(r"v\d+$", "", value[6:], flags=re.I)
        require(re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})", identifier), "Invalid arXiv ID")
        return "arxiv:" + identifier.lower()
    if value.lower().startswith("doi:"):
        identifier = value[4:].lower()
        require(re.fullmatch(r"10\.\d{4,9}/\S+", identifier), "Invalid DOI")
        return "doi:" + identifier
    if value.startswith("openreview:"):
        require(re.fullmatch(r"[A-Za-z0-9_-]+", value[11:]), "Invalid OpenReview ID")
        return value
    if value.startswith("url:"):
        return "url:" + canonical_url(value[4:])
    raise ValueError("Use an arXiv ID, DOI, OpenReview ID, or canonical paper HTTPS URL")


def six_months_before(day):
    today = iso_day(day)
    month_index = today.year * 12 + today.month - 1 - 6
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1])).isoformat()


def empty_state():
    return {"schema_version": 1, "introduced": {"repositories": {}, "papers": {}},
            "receipts": {}, "observations": {}}


def context_for(day, state):
    today = iso_day(day)
    previous = [key for key in state["observations"] if key < day]
    recent = {key: value for key, value in state["introduced"]["papers"].items()
              if today - timedelta(days=7) <= iso_day(value) < today}
    return {
        "date": day, "timezone": "Asia/Seoul",
        "github_window_start": (today - timedelta(days=7)).isoformat(),
        "paper_first_publication_cutoff": six_months_before(day),
        "cncf_window_start": (today - timedelta(days=3)).isoformat(),
        "introduced_repositories": sorted(state["introduced"]["repositories"]),
        "papers_introduced_last_seven_days": recent,
        "previous_snapshot": state["observations"][max(previous)] if previous else None,
        "first_run": not any(state["introduced"][key] for key in ("repositories", "papers")),
    }


def source_list(item):
    sources = item.get("sources")
    require(isinstance(sources, list) and bool(sources), "At least one source is required")
    for source in sources:
        safe_url(source)


def check_fields(value, definition):
    require(isinstance(value, dict), "Expected an object")
    require(not set(value).difference(definition["properties"]), "Unexpected fields in public issue payload")
    require(set(definition["required"]).issubset(value), "Missing required public issue fields")


def snapshot_rows(snapshot):
    check_fields(snapshot, SCHEMA["$defs"]["snapshot"])
    aware_time(snapshot.get("captured_at"))
    url = urlsplit(safe_url(snapshot.get("source")))
    require(url.hostname == "github.com" and url.path.rstrip("/") == "/trending"
            and parse_qs(url.query).get("since") == ["weekly"],
            "GitHub snapshot must use weekly Trending")
    entries = snapshot.get("entries")
    require(isinstance(entries, list) and 1 <= len(entries) <= 10, "Invalid snapshot size")
    rows = {}
    for expected, entry in enumerate(entries, 1):
        check_fields(entry, SCHEMA["$defs"]["snapshot"]["properties"]["entries"]["items"])
        key = repository_id(entry.get("repository"))
        require(type(entry.get("rank")) is int and entry["rank"] == expected and key not in rows,
                "Invalid snapshot ranks")
        stars = entry.get("weekly_stars")
        require(stars is None or (type(stars) is int and stars >= 0), "Invalid weekly stars")
        rows[key] = entry
    return rows


def validate_issue(issue, state):
    check_fields(issue, SCHEMA)
    require(type(issue.get("schema_version")) is int and issue["schema_version"] in (1, 2), "Invalid issue schema")
    editorial = issue["schema_version"] == 2
    revision = issue.get("revision", 1)
    require(type(revision) is int and revision >= 1, "Invalid revision number")
    if revision > 1:
        require(isinstance(issue.get("supersedes"), str)
                and re.fullmatch(r"[a-f0-9]{64}", issue["supersedes"]), "Revision needs a superseded digest")
        text(issue.get("revision_note"), "revision note")
    else:
        require("supersedes" not in issue and "revision_note" not in issue, "First revision cannot supersede a report")
    today = iso_day(issue.get("date"))
    generated = aware_time(issue.get("generated_at"))
    require(generated.astimezone(KST).date() == today, "Generated timestamp must match issue day in KST")
    text(issue.get("headline"), "headline")
    require(isinstance(issue.get("summary"), list) and len(issue["summary"]) == 3,
            "Exactly three overview lines are required")
    for line in issue["summary"]:
        text(line, "summary line")
    coverage = issue.get("coverage", {})
    check_fields(coverage, SCHEMA["properties"]["coverage"])
    for name in SECTIONS:
        require(isinstance(coverage.get(name), dict), "Missing coverage: " + name)
        source = coverage[name]
        check_fields(source, SCHEMA["$defs"]["coverage"])
        require(source.get("status") in ("ok", "partial", "unavailable"), "Invalid coverage status")
        text(source.get("note"), name + " coverage note")
        source_list(source)

    arrays = {"repositories": (10, "repository", "github"), "papers": (5, "paper", "papers"),
              "discussions": (12 if editorial else 7, "discussion", "community"), "cncf": (5, "change", "cncf")}
    for name, (maximum, definition, source_name) in arrays.items():
        require(isinstance(issue.get(name), list) and len(issue[name]) <= maximum,
                name + " exceeds the item limit or is not an array")
        require(not issue[name] or coverage[source_name]["status"] != "unavailable",
                "Unavailable coverage cannot contain supposedly verified items")
        for item in issue[name]:
            check_fields(item, SCHEMA["$defs"][definition])
            if "tags" in item:
                require(item["tags"] == normalize_tags(item["tags"]),
                        "Stored tags must be unique, sorted canonical IDs")
            require(not editorial or "tags" in item, "Version 2 items require tags")
            safe_url(item.get("url"))
            source_list(item)

    snapshot = issue.get("github_snapshot")
    snapshot_ids = {}
    if snapshot is not None:
        snapshot_ids = snapshot_rows(snapshot)
        moment = aware_time(snapshot.get("captured_at"))
        require(moment.astimezone(KST).date() == today and moment <= generated,
                "GitHub snapshot time must precede generation on the same KST day")
        require(len(snapshot_ids) == 10 or coverage["github"]["status"] != "ok",
                "A partial snapshot needs partial coverage")
    else:
        require(not issue["repositories"] and coverage["github"]["status"] != "ok",
                "Repositories require an observed snapshot")
    previous_snapshot = issue.get("github_previous_snapshot")
    if previous_snapshot is not None:
        snapshot_rows(previous_snapshot)
        require(aware_time(previous_snapshot["captured_at"]).astimezone(KST).date() < today,
                "Comparison snapshot must be from an earlier day")

    seen = set()
    for repo in issue["repositories"]:
        key = repository_id(repo.get("repository"))
        require(key not in seen, "Duplicate repository")
        seen.add(key)
        previous = state["introduced"]["repositories"].get(key)
        require(previous is None or previous == issue["date"], key + " already introduced")
        require(key in snapshot_ids and repo.get("rank") == snapshot_ids[key]["rank"],
                "Repository rank must match the snapshot")
        require(canonical_url(repo["url"]).lower() == "https://github.com/" + key,
                "Repository URL must match owner/repository")
        for field in ("summary", "why_now", "use_case", "caution"):
            text(repo.get(field), field)
        if "novelty" in repo:
            require(repo["novelty"] in ("first_observed", "new_entry", "first_introduction"),
                    "Invalid repository novelty label")
        if repo.get("novelty") == "new_entry":
            comparison = previous_snapshot or context_for(issue["date"], state)["previous_snapshot"]
            require(comparison is not None, "New entry needs a previous observed snapshot")
            require(key not in {repository_id(row["repository"]) for row in comparison["entries"]},
                    "New entry was already in the previous snapshot")

    seen.clear()
    cutoff = iso_day(six_months_before(issue["date"]))
    for paper in issue["papers"]:
        key = canonical_paper_id(paper.get("id"))
        require(key not in seen, "Duplicate paper")
        seen.add(key)
        published = iso_day(paper.get("first_published"))
        require(cutoff <= published <= today, "Paper is outside the six-month first-publication window")
        previous = state["introduced"]["papers"].get(key)
        require(previous is None or previous == issue["date"]
                or iso_day(previous) < today - timedelta(days=7),
                key + " was introduced in the last seven days")
        require(paper.get("evidence") in ("full_text", "abstract_only"), "Invalid paper reading evidence")
        require(not editorial or paper["evidence"] == "full_text", "New papers require verified full text")
        topics = paper.get("topics")
        require(isinstance(topics, list) and 1 <= len(topics) <= 5, "Paper topics are required")
        for topic in topics:
            text(topic, "topic")
        for field in ("title", "abstract_summary", "method", "findings", "limitations", "practical_value"):
            text(paper.get(field), field)
    require(len(issue["papers"]) == 5 or coverage["papers"]["status"] != "ok",
            "Fewer than five papers needs partial/unavailable coverage")

    seen.clear()
    for story in issue["discussions"]:
        key = canonical_url(story["url"])
        require(key not in seen, "Duplicate discussion: merge coverage of the same story")
        seen.add(key)
        if editorial:
            require(not any(field in story for field in ("summary", "significance", "caveat")),
                    "Version 2 community is link-only")
        for field in (("title",) if editorial else ("title", "summary", "significance", "caveat")):
            text(story.get(field), field)
    seen.clear()
    for change in issue["cncf"]:
        key = canonical_url(change["url"])
        require(key not in seen, "Duplicate CNCF change")
        seen.add(key)
        published = iso_day(change.get("published"))
        require(today - timedelta(days=3) <= published <= today, "CNCF change is outside the three-day window")
        for field in ("title", "category", "summary", "impact"):
            text(change.get(field), field)
    if editorial:
        require("lead" in issue, "Version 2 needs one editorial lead")
        if any(issue[name] for name in ITEM_COLLECTIONS.values()):
            lead_item(issue)
        else:
            require(issue["lead"] is None, "Empty issue must not invent a lead")
    if "github_featured" in issue:
        picks = issue["github_featured"]
        require(isinstance(picks, list) and min(2, len(issue["repositories"])) <= len(picks) <= min(3, len(issue["repositories"])),
                "Choose two or three featured repositories, or all available if fewer")
        keys = [repository_id(value) for value in picks]
        require(len(keys) == len(set(keys)) and set(keys).issubset(
            {repository_id(item["repository"]) for item in issue["repositories"]}), "Invalid featured repository")
    if "teams" in issue:
        config = issue["teams"]
        check_fields(config, SCHEMA["properties"]["teams"])
        require(isinstance(config["spotlight"], list) and 1 <= len(config["spotlight"]) <= 3,
                "Teams spotlight needs one to three short paragraphs")
        for paragraph in config["spotlight"]:
            require(len(text(paragraph, "spotlight")) <= 500, "Teams spotlight paragraph is too long")
        require(isinstance(config["highlights"], list) and len(config["highlights"]) <= 3, "At most three Teams highlights")
        selected = set()
        for entry in config["highlights"]:
            check_fields(entry, SCHEMA["properties"]["teams"]["properties"]["highlights"]["items"])
            require(entry["section"] in ITEM_COLLECTIONS, "Invalid highlight section")
            require(len(text(entry["text"], "highlight")) <= 160, "Teams highlight is too long")
            key = canonical_url(entry["url"])
            require(key not in selected and any(canonical_url(item["url"]) == key
                    for item in issue[ITEM_COLLECTIONS[entry["section"]]]), "Teams highlight must reference one included item")
            selected.add(key)
    return issue


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def issue_digest(issue):
    return hashlib.sha256(json_text(issue).encode("utf-8")).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", delete=False) as output:
        output.write(json_text(value))
        temporary = Path(output.name)
    temporary.replace(path)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(root):
    path = root / ".local" / "state.json"
    state = load_json(path) if path.exists() else empty_state()
    require(state.get("schema_version") == 1, "Unsupported history schema")
    return state


def save_state(root, state):
    atomic_json(root / ".local" / "state.json", state)


def introduce(issue, state):
    for repo in issue["repositories"]:
        key = repository_id(repo["repository"])
        state["introduced"]["repositories"][key] = min(
            issue["date"], state["introduced"]["repositories"].get(key, issue["date"]))
    for paper in issue["papers"]:
        key = canonical_paper_id(paper["id"])
        state["introduced"]["papers"][key] = max(
            issue["date"], state["introduced"]["papers"].get(key, issue["date"]))


def delivery_key(issue):
    revision = issue.get("revision", 1)
    return issue["date"] if revision == 1 else issue["date"] + ":r" + str(revision)


def stage_issue(root, issue, expected_digest=None):
    state = load_state(root)
    issue = copy.deepcopy(issue)
    require(issue.get("schema_version") == 2, "New staging requires schema version 2")
    for name in ITEM_COLLECTIONS.values():
        for item in issue.get(name, []):
            require("tags" in item, "New items require tags from tags.json")
            item["tags"] = normalize_tags(item["tags"])
    comparison = context_for(issue["date"], state)["previous_snapshot"]
    if comparison is not None and "github_previous_snapshot" not in issue:
        issue["github_previous_snapshot"] = comparison
    validate_issue(issue, state)
    path = root / ".local" / "drafts" / (issue["date"] + ".json")
    original = load_json(path) if path.exists() else None
    revision = issue.get("revision", 1)
    published = root / "reports" / (issue["date"] + ".json")
    public_issue = load_json(published) if published.exists() else None
    if expected_digest is not None:
        require(original is not None and issue_digest(original) == expected_digest,
                "Original draft digest changed")
        require(revision == original.get("revision", 1) + 1, "Use the exact next revision")
        require(issue.get("supersedes") == expected_digest, "Superseded digest mismatch")
        old_receipt = state["receipts"].get(delivery_key(original))
        require(old_receipt is None or old_receipt["complete"], "Cannot revise during partial delivery")
        require(public_issue is None or issue_digest(public_issue) == expected_digest,
                "Public base digest changed")
    else:
        require((original is None and revision == 1)
                or (original is not None and original.get("revision", 1) == revision),
                "Use the explicit revise command to create a new revision")
    receipt = state["receipts"].get(delivery_key(issue))
    require(receipt is None or receipt["digest"] == issue_digest(issue),
            "Cannot rewrite an issue after delivery has started")
    for mode in ("preview", "published"):
        sent_digest = state.get("digest_receipts", {}).get(delivery_key(issue) + ":digest:" + mode)
        require(sent_digest is None or sent_digest["issue_digest"] == issue_digest(issue),
                "Cannot rewrite an issue after digest delivery has started")
    if public_issue is not None and issue_digest(public_issue) != issue_digest(issue):
        require(revision == public_issue.get("revision", 1) + 1
                and issue.get("supersedes") == issue_digest(public_issue)
                and (expected_digest is not None or
                     (original is not None and original.get("revision", 1) == revision)),
                "Cannot rewrite an already published issue without revise")
    if expected_digest is not None:
        atomic_json(root / ".local" / "revisions" / issue["date"]
                    / ("r" + str(original.get("revision", 1)) + "-" + expected_digest + ".json"), original)
    atomic_json(path, issue)
    if issue["github_snapshot"] is not None:
        state["observations"][issue["date"]] = issue["github_snapshot"]
    save_state(root, state)


def revise_issue(root, issue, expected_digest):
    stage_issue(root, issue, expected_digest=expected_digest)


def load_draft(root, day):
    iso_day(day)
    path = root / ".local" / "drafts" / (day + ".json")
    require(path.exists(), "No prepared report for " + day + "; do not send yesterday's issue")
    issue = load_json(path)
    require(issue["date"] == day, "Draft filename/date mismatch")
    validate_issue(issue, load_state(root))
    return issue


def report_text(issue):
    revision = issue.get("revision", 1)
    revision_label = " · 수정본 r" + str(revision) if revision > 1 else ""
    lines = ["Daily Tech Brief | " + issue["date"] + " (KST)" + revision_label, issue["headline"]]
    if revision > 1:
        lines.append("수정 내용: " + issue["revision_note"])
    lines.extend(["", "Technical Spotlight" if issue.get("lead") else "오늘의 세 줄",
                  *["• " + line for line in issue["summary"]]])
    if issue.get("lead"):
        lines.append("선정 항목: " + lead_item(issue)["url"])
    lines.append("")
    field_map = [
        ("GitHub", "github", "repositories",
         (("summary", "개요"), ("why_now", "주목 이유"), ("use_case", "활용"), ("caution", "주의"))),
        ("AI 논문", "papers", "papers",
         (("abstract_summary", "초록 요약"), ("method", "방법"), ("findings", "결과"),
          ("limitations", "한계"), ("practical_value", "실무 의미"))),
        ("HN · 긱뉴스 · Reddit", "community", "discussions",
         (("summary", "핵심"), ("significance", "의미"), ("caveat", "사실과 의견"))),
        ("CNCF", "cncf", "cncf", (("summary", "변경"), ("impact", "영향"))),
    ]
    for title, coverage, name, fields in field_map:
        lines.extend(["", title, issue["coverage"][coverage]["note"]])
        for number, item in enumerate(issue[name], 1):
            lines.extend(["", str(number) + ". " + item.get("title", item.get("repository", ""))])
            if name == "discussions" and issue["schema_version"] == 2:
                lines.append(item["url"])
                related = community_sources(item)
                if related:
                    lines.append(" · ".join(related))
                continue
            if item.get("tags"):
                lines.append("태그: " + " · ".join(TAGS[tag]["label"] for tag in item["tags"]))
            if name == "papers":
                evidence = "본문 확인" if item["evidence"] == "full_text" else "초록만 확인"
                lines.append("최초 발표: " + item["first_published"] + " · " + evidence)
            if name == "repositories":
                lines.append("주간 Trending " + str(item["rank"]) + "위")
            for field, label in fields:
                lines.append(label + ": " + item[field])
            lines.extend(["원문: " + item["url"], "출처: " + " · ".join(item["sources"])])
    lines.extend(["", "보고서 아카이브: https://hellices.github.io/daily-tech-brief/",
                  "아직 공개하지 않은 보고서는 내용을 확인한 뒤 Scout에서 해당 날짜의 게시를 승인해 주세요.",
                  "공개 자료만 사용했습니다. 수집 기준: " + issue["generated_at"]])
    return "\n".join(lines)


def delivery_parts(issue, max_bytes=MAX_PART_BYTES):
    require(type(max_bytes) is int and max_bytes >= 512, "Message byte limit is too small")
    content = report_text(issue)
    budget = max_bytes - 160
    chunks, buffer = [], ""
    for line in content.splitlines(keepends=True):
        if len((buffer + line).encode("utf-8")) <= budget:
            buffer += line
            continue
        if buffer:
            chunks.append(buffer)
            buffer = ""
        for char in line:
            if len((buffer + char).encode("utf-8")) > budget:
                chunks.append(buffer)
                buffer = ""
            buffer += char
    if buffer:
        chunks.append(buffer)
    revision_label = " · 수정본 r" + str(issue["revision"]) if issue.get("revision", 1) > 1 else ""
    return ["Daily Tech Brief " + issue["date"] + revision_label + " [" + str(index + 1) + "/" + str(len(chunks)) + "]\n\n" + part
            for index, part in enumerate(chunks)]


def record_receipt(issue, state, digest, part, total):
    require(digest == issue_digest(issue), "Receipt digest mismatch")
    require(total == len(delivery_parts(issue)), "Delivery part count mismatch")
    require(type(part) is int and 0 <= part < total, "Invalid delivery part index")
    result = copy.deepcopy(state)
    key = delivery_key(issue)
    previous = result["receipts"].get(key)
    require(previous is None or (previous["digest"] == digest and previous["total"] == total),
            "Conflicting delivery receipt")
    receipt = previous or {"digest": digest, "total": total, "sent_parts": []}
    receipt["sent_parts"] = sorted(set(receipt["sent_parts"] + [part]))
    receipt["complete"] = len(receipt["sent_parts"]) == total
    result["receipts"][key] = receipt
    if receipt["complete"]:
        introduce(issue, result)
    return result


def promote_issue(root, day, digest):
    issue = load_draft(root, day)
    require(issue_digest(issue) == digest, "Approved digest does not match current draft")
    target = root / "reports" / (day + ".json")
    if target.exists():
        previous = load_json(target)
        require(issue_digest(previous) == digest or
                (issue.get("revision", 1) == previous.get("revision", 1) + 1
                 and issue.get("supersedes") == issue_digest(previous)),
                "Public base digest changed; review this revision again")
    atomic_json(target, issue)


def record_publication(root, day, digest):
    iso_day(day)
    issue = load_json(root / "reports" / (day + ".json"))
    require(issue["date"] == day and issue_digest(issue) == digest, "Publication digest mismatch")
    state = load_state(root)
    validate_issue(issue, state)
    introduce(issue, state)
    state.setdefault("publications", {})[day] = digest
    save_state(root, state)


def link(url, label):
    return '<a href="' + escape(safe_url(url), quote=True) + '" target="_blank" rel="noopener noreferrer">' + escape(label) + "</a>"


def fields_html(item, fields):
    return "<dl>" + "".join('<dt class="field-label">' + escape(label) + "</dt><dd>"
                           + escape(item[key]) + "</dd>" for key, label in fields) + "</dl>"


def sources_html(item):
    return '<p class="source-links">출처: ' + " · ".join(
        link(url, urlsplit(url).hostname or "원문") for url in dict.fromkeys(item["sources"])) + "</p>"


def community_sources(item):
    primary = canonical_url(item["url"])
    return [url for url in dict.fromkeys(item["sources"]) if canonical_url(url) != primary]


def community_sources_html(item):
    labels = {"news.ycombinator.com": "HN", "news.hada.io": "긱뉴스"}
    links = []
    for url in community_sources(item):
        host = urlsplit(url).hostname
        label = "Reddit" if host == "reddit.com" or host.endswith(".reddit.com") else labels.get(host, host)
        links.append(link(url, label))
    return '<p class="source-links">' + " · ".join(links) + "</p>" if links else ""


def issue_title(issue):
    return issue["date"] + " · " + issue["headline"]


def lead_item(issue):
    lead = issue.get("lead")
    require(isinstance(lead, dict), "Invalid editorial lead")
    check_fields(lead, SCHEMA["properties"]["lead"]["anyOf"][1])
    require(lead.get("section") in ITEM_COLLECTIONS, "Unknown lead section")
    target = canonical_url(lead.get("url"))
    matches = [item for item in issue[ITEM_COLLECTIONS[lead["section"]]]
               if canonical_url(item["url"]) == target]
    require(len(matches) == 1, "The lead must reference exactly one current item")
    return matches[0]


def item_anchor(section, item):
    if section == "github":
        identifier = repository_id(item["repository"])
    elif section == "papers":
        identifier = canonical_paper_id(item["id"])
    else:
        identifier = canonical_url(item["url"])
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
    return "item-" + section + "-" + digest


def tags_html(tags, base):
    if not tags:
        return ""
    return '<div class="tag-list" aria-label="태그">' + "".join(
        '<a class="tag-chip" href="' + base + "index.html#" + urlencode({"tag": tag}) + '">'
        + escape(TAGS[tag]["label"]) + "</a>" for tag in tags) + "</div>"


def featured_repositories(issue):
    repositories = {repository_id(item["repository"]): item for item in issue["repositories"]}
    chosen = issue.get("github_featured", [item["repository"] for item in issue["repositories"][:3]])
    return [repositories[repository_id(name)] for name in chosen]


def github_overview_html(issue):
    current = {repository_id(item["repository"]): item for item in issue["repositories"]}
    snapshot = issue.get("github_snapshot")
    if snapshot is None:
        return ""
    picks = featured_repositories(issue)
    selected = {repository_id(item["repository"]) for item in picks}
    output = [
        '<table class="github-table"><caption>Weekly Top 10 · 관측 순위와 주간 stars</caption>',
        '<thead><tr><th scope="col">Rank</th><th scope="col">Repository</th>'
        '<th scope="col">한 줄 특징</th><th scope="col">Stars / week</th></tr></thead><tbody>',
    ]
    for row in snapshot["entries"]:
        key = repository_id(row["repository"])
        item = current.get(key)
        description = item["summary"] if item else "이번 호 상세 제외"
        stars = format(row["weekly_stars"], ",") if row["weekly_stars"] is not None else "미확인"
        url = item["url"] if item else "https://github.com/" + row["repository"]
        output.extend([
            '<tr class="repo-overview-row"><td class="repo-rank" data-label="Rank">' + str(row["rank"]) + "</td>",
            '<td class="repo-name" data-label="Repository">' + link(url, row["repository"]),
        ])
        if key in selected:
            output.append('<span class="repo-pick-label">Editor’s pick</span>')
        if item:
            output.append('<a class="repo-detail-link" href="#' + item_anchor("github", item) + '">상세</a>')
        output.extend([
            "</td><td class=\"repo-description\" data-label=\"한 줄 특징\">" + escape(description) + "</td>",
            '<td class="repo-stars" data-label="Stars / week">' + stars + "</td></tr>",
        ])
    output.append("</tbody></table>")

    def detail(item, featured):
        cls = "article-item repo-feature" if featured else "article-item repo-extra"
        badge = {"new_entry": "신규 진입", "first_observed": "첫 관측",
                 "first_introduction": "첫 소개"}.get(item.get("novelty"), "첫 소개")
        return "".join([
            '<article class="' + cls + '" id="' + item_anchor("github", item) + '">',
            '<p class="meta">#' + str(item["rank"]) + " · " + badge + "</p>",
            "<h3>" + link(item["url"], item["repository"]) + "</h3>",
            '<p class="repo-feature-summary">' + escape(item["summary"]) + "</p>",
            '<p class="repo-pick-reason">' + escape(item["why_now"]) + "</p>",
            '<details class="repo-details"><summary>활용 · 주의 · 태그</summary>',
            fields_html(item, (("use_case", "활용"), ("caution", "주의"))),
            tags_html(item.get("tags", []), "../../"), sources_html(item), "</details></article>",
        ])

    if picks:
        output.append('<div class="github-picks"><h3>Editor’s Picks</h3>')
        output.extend(detail(item, True) for item in picks)
        output.append("</div>")
    others = [item for item in issue["repositories"] if repository_id(item["repository"]) not in selected]
    if others:
        output.append('<details class="repo-overflow"><summary>나머지 ' + str(len(others))
                      + '개 레포 상세 보기</summary><div class="repo-overflow-body">')
        output.extend(detail(item, False) for item in others)
        output.append("</div></details>")
    return "\n".join(output)


def shorten(value, limit):
    if len(value) <= limit:
        return value
    prefix = value[:limit - 1]
    return prefix.rsplit(" ", 1)[0] + "…" if " " in prefix else prefix + "…"


def teams_digest_html(issue, published=False):
    config = issue.get("teams")
    paragraphs = config["spotlight"] if config else [shorten(issue["summary"][0], 420)]
    highlights = config["highlights"] if config else []
    if config is None:
        for section in ("github", "papers", "cncf"):
            choices = featured_repositories(issue) if section == "github" else issue[ITEM_COLLECTIONS[section]]
            item = next((item for item in choices if not issue.get("lead")
                         or canonical_url(item["url"]) != canonical_url(issue["lead"]["url"])), None)
            if item:
                highlights.append({"section": section, "url": item["url"],
                                   "text": shorten(item.get("summary", item.get("title", "")), 110)})
    base = "https://hellices.github.io/daily-tech-brief/"
    day_url = base + "daily/" + issue["date"] + "/"
    suffix = " · Updated" if issue.get("revision", 1) > 1 else ""
    output = ["<p><strong>Daily Tech Brief · " + issue["date"] + suffix + "</strong></p>",
              "<p><strong>Technical Spotlight</strong><br>" + escape(shorten(issue["headline"], 200)) + "</p>"]
    output.extend("<p>" + escape(paragraph) + "</p>" for paragraph in paragraphs)
    if highlights:
        output.extend(["<p><strong>Highlights</strong></p>", "<ul>"])
        for entry in highlights[:3]:
            item = next(item for item in issue[ITEM_COLLECTIONS[entry["section"]]]
                        if canonical_url(item["url"]) == canonical_url(entry["url"]))
            label = item.get("title", item.get("repository", ""))
            if entry["section"] == "papers":
                label = label.split(": ", 1)[0]
            href = day_url + "#" + item_anchor(entry["section"], item) if published else item["url"]
            output.append("<li><strong>" + link(href, shorten(label, 110)) + "</strong><br>"
                          + escape(entry["text"]) + "</li>")
        output.append("</ul>")
    if published:
        output.append("<p><strong>" + link(day_url, "전체 보고서 읽기") + "</strong><br>"
                      + " · ".join(link(day_url + "#" + section, SECTION_LABELS[section]) for section in SECTIONS)
                      + "</p>")
    else:
        output.append("<p><strong>상세 보고서 게시 승인 대기</strong><br>"
                      "원문 링크로 먼저 확인할 수 있습니다. Scout에서 전체 미리보기를 확인하고 게시를 승인해 주세요.</p>"
                      "<p>" + link(base, "기존 보고서 아카이브") + "</p>")
    message = "\n".join(output)
    require(len(message.encode("utf-8")) <= 8000, "Teams digest exceeds the single-message budget")
    return message


def text_digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_digest_receipt(issue, state, digest, message, message_id, mode):
    require(mode in ("preview", "published"), "Invalid digest mode")
    require(digest == text_digest(message), "Teams message digest mismatch")
    text(message_id, "Teams message ID")
    result = copy.deepcopy(state)
    key = delivery_key(issue) + ":digest:" + mode
    receipt = {"issue_digest": issue_digest(issue), "message_digest": digest,
               "message_id": message_id, "complete": True, "mode": mode}
    prior = result.setdefault("digest_receipts", {}).get(key)
    require(prior is None or prior == receipt, "Conflicting Teams digest receipt")
    result["digest_receipts"][key] = receipt
    return result


def digest_payload(root, day, mode=None):
    issue = load_draft(root, day)
    state = load_state(root)
    published = state.get("publications", {}).get(day) == issue_digest(issue)
    if mode is not None:
        require(mode != "published" or published, "Current report publication is not verified")
        published = mode == "published"
    mode = "published" if published else "preview"
    message = teams_digest_html(issue, published)
    key = delivery_key(issue) + ":digest:" + mode
    prior = state.get("digest_receipts", {}).get(key)
    require(prior is None or (prior["issue_digest"] == issue_digest(issue)
                             and prior["message_digest"] == text_digest(message)),
            "Digest changed after sending; use a new report revision")
    return {"date": day, "revision": issue.get("revision", 1), "mode": mode, "content_type": "html",
            "issue_digest": issue_digest(issue), "message_digest": text_digest(message),
            "already_sent": prior is not None, "message": None if prior else message}


def build_search_index(issues):
    items, counts = [], {}
    for issue in sorted(issues, key=lambda entry: entry["date"], reverse=True):
        for section, collection in ITEM_COLLECTIONS.items():
            for item in issue[collection]:
                tags = item.get("tags", [])
                for tag in tags:
                    counts[tag] = counts.get(tag, 0) + 1
                title = item.get("title", item.get("repository", ""))
                body = " ".join(value for key, value in item.items()
                                if isinstance(value, str) and key not in
                                ("id", "url", "title", "repository", "novelty", "evidence"))
                terms = " ".join(" ".join([tag, TAGS[tag]["label"], *TAGS[tag]["aliases"]]) for tag in tags)
                anchor = item_anchor(section, item)
                opening = []
                if issue.get("lead") is None or (
                        section == issue["lead"]["section"]
                        and canonical_url(item["url"]) == canonical_url(issue["lead"]["url"])):
                    opening = [issue["headline"], *issue["summary"]]
                items.append({
                    "id": issue["date"] + ":" + anchor, "date": issue["date"],
                    "section": section, "section_label": SECTION_LABELS[section],
                    "title": title, "issue_title": issue_title(issue),
                    "summary": item.get("abstract_summary", item.get("summary", title)), "body": body,
                    "search_text": " ".join([issue["date"], title, body, item["url"],
                                             SECTION_LABELS[section], terms, *item.get("topics", []),
                                             *opening, issue["coverage"][section]["note"]]),
                    "tags": tags, "href": "./daily/" + issue["date"] + "/index.html#" + anchor,
                })
    return {
        "version": 1, "report_dates": sorted({issue["date"] for issue in issues}, reverse=True),
        "sections": [{"id": key, "label": label} for key, label in SECTION_LABELS.items()],
        "tags": [{**TAGS[tag], "count": counts[tag]} for tag in sorted(counts, key=lambda key: (-counts[key], key))],
        "items": items,
    }


def search_html(index):
    tags = "".join(
        '<label class="tag-option"><input type="checkbox" name="tag" value="' + escape(tag["id"])
        + '">' + escape(tag["label"]) + ' <span class="tag-count">' + str(tag["count"]) + "</span></label>"
        for tag in index["tags"])
    if not tags:
        tags = '<p class="meta">첫 보고서가 게시되면 태그가 표시됩니다.</p>'
    options = '<option value="">전체 섹션</option>' + "".join(
        '<option value="' + key + '">' + escape(label) + "</option>" for key, label in SECTION_LABELS.items())
    payload = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return "".join([
        '<section id="archive-search"><h2>보고서 찾기</h2>',
        '<p class="search-help">누적된 보고서의 제목·요약·상세 내용을 검색합니다. 조건은 함께 적용됩니다.</p>',
        '<form id="search-form" role="search"><div class="search-controls">',
        '<label class="search-query-label" for="search-query">검색어',
        '<input id="search-query" type="search" placeholder="예: agent memory, 쿠버네티스" autocomplete="off"></label>',
        '<label for="search-section">섹션<select id="search-section">', options, "</select></label>",
        '<label for="search-from">시작일<input id="search-from" type="date"></label>',
        '<label for="search-to">종료일<input id="search-to" type="date"></label></div>',
        '<fieldset class="tag-filter"><legend>태그 · 여러 개 선택하면 모두 포함</legend>',
        '<div id="search-tags">', tags, '</div></fieldset>',
        '<div class="search-actions"><button type="submit">검색</button>',
        '<button id="search-reset" type="button">초기화</button></div></form>',
        '<p id="search-status" role="status" aria-live="polite">검색 기능을 준비하고 있습니다.</p>',
        '<div id="search-results" class="search-results" hidden></div>',
        '<button id="search-more" type="button" hidden>더 보기</button>',
        '<noscript><p class="notice">검색에는 JavaScript가 필요합니다. 아래 날짜별 목록에서 모든 보고서를 읽을 수 있습니다.</p></noscript></section>',
        '<script id="search-data" type="application/json">', payload, "</script>",
    ])


def render_issue(issue):
    result = [
        '<header class="hero" data-issue-digest="' + issue_digest(issue)
        + '"><p class="eyebrow">DAILY TECH BRIEF · ' + escape(issue["date"]) + '</p>',
        "<h1>" + escape(issue_title(issue)) + "</h1>",
        '<p class="meta">수집 기준 ' + escape(issue["generated_at"]) + " · 한국 시간</p></header>",
    ]
    if issue.get("revision", 1) > 1:
        result.append('<p class="revision-note">수정본 r' + str(issue["revision"]) + " · "
                      + escape(issue["revision_note"]) + "</p>")
    if issue.get("lead"):
        lead = lead_item(issue)
        result.extend(['<div class="lead-story"><p class="eyebrow">Technical Spotlight</p>',
                       *['<p class="lead-paragraph">' + escape(line) + "</p>" for line in issue["summary"]],
                       '<a class="lead-jump" href="#' + item_anchor(issue["lead"]["section"], lead)
                       + '">선정 항목 자세히 읽기</a></div>'])
    else:
        result.append('<ul class="summary-list">' + "".join("<li>" + escape(line) + "</li>" for line in issue["summary"]) + "</ul>")
    result.extend([
        '<nav class="section-nav" aria-label="보고서 목차"><a href="#github">GitHub</a>'
        '<a href="#papers">AI 논문</a><a href="#community">커뮤니티</a><a href="#cncf">CNCF</a></nav>',
    ])
    field_map = [
        ("github", "GitHub · 주간 Trending", "repositories",
         (("summary", "개요"), ("why_now", "주목 이유"), ("use_case", "활용"), ("caution", "주의"))),
        ("papers", "AI 논문 · 다섯 편의 관점", "papers",
         (("method", "핵심 방법"), ("findings", "주요 결과"), ("limitations", "한계"), ("practical_value", "실무 의미"))),
        ("community", "HN · 긱뉴스 · Reddit", "discussions",
         (("summary", "핵심 내용"), ("significance", "주목할 이유"), ("caveat", "사실과 의견"))),
        ("cncf", "CNCF · 최근 주요 변경", "cncf", (("summary", "변경 내용"), ("impact", "영향과 대응"))),
    ]
    for section, heading, name, fields in field_map:
        if section == "papers" and issue["schema_version"] == 2:
            heading = "AI 논문 · 본문으로 읽은 " + str(len(issue["papers"])) + "편"
        result.extend(['<section id="' + section + '"><h2>' + heading + "</h2>",
                       '<p class="coverage-note">' + escape(issue["coverage"][section]["note"]) + "</p>"])
        if not issue[name]:
            result.append('<p class="notice">이번 호에는 조건을 충족하는 신규 항목이 없습니다.</p>')
        if section == "github" and issue["schema_version"] == 2:
            result.extend([github_overview_html(issue), "</section>"])
            continue
        for index, item in enumerate(issue[name], 1):
            title = item.get("title", item.get("repository", ""))
            compact = name == "discussions" and issue["schema_version"] == 2
            classes = "article-item community-link" if compact else "article-item"
            result.extend(['<article class="' + classes + '" id="' + item_anchor(section, item)
                           + '"><div class="item-heading">',
                           '<span class="item-number">' + str(index).zfill(2) + "</span>",
                           "<h3>" + link(item["url"], title) + "</h3></div>"])
            if compact:
                result.extend([community_sources_html(item), "</article>"])
                continue
            result.append(tags_html(item.get("tags", []), "../../"))
            if name == "repositories":
                labels = {"first_observed": "첫 관측", "new_entry": "신규 진입", "first_introduction": "첫 소개"}
                badge = labels.get(item.get("novelty"), "첫 소개")
                result.append('<p class="meta"><span class="badge">' + badge + "</span> 주간 Trending "
                              + str(item["rank"]) + "위</p>")
            if name == "papers":
                evidence = "본문 기반" if item["evidence"] == "full_text" else "초록만 확인 · 상세 검증 제한"
                result.extend(['<p class="meta">최초 발표 ' + escape(item["first_published"]) + " · "
                               + escape(" / ".join(item["topics"])) + " · " + evidence + "</p>",
                               '<p class="item-summary">' + escape(item["abstract_summary"]) + "</p>",
                               '<details class="paper-details"><summary>방법 · 결과 · 한계 · 실무 의미</summary>',
                               fields_html(item, fields), "</details>"])
            else:
                if name == "cncf":
                    result.append('<p class="meta">' + escape(item["published"]) + " · " + escape(item["category"]) + "</p>")
                result.append(fields_html(item, fields))
            result.extend([sources_html(item), "</article>"])
        result.append("</section>")
    result.append('<p class="issue-footer">선정 기준: GitHub 주간 상위 10개 중 미소개 레포 · 최근 6개월 논문 중 7일 중복 제외 · CNCF 최근 3일.</p>')
    return "\n".join(result)


def render_home(issues):
    body = [
        '<header class="hero"><p class="eyebrow">DAILY TECH BRIEF</p>',
        "<h1>매일 오전 9시, 개발자를 위한 기술 브리핑</h1>",
        '<p class="lede">GitHub · AI Papers · Community · CNCF</p>',
        "<p>오늘의 핵심만 먼저 읽고, 필요한 내용은 깊게 살펴보세요.</p></header>",
        search_html(build_search_index(issues)),
        '<section id="date-archive"><h2>보고서 아카이브</h2>',
    ]
    if not issues:
        body.append('<p class="empty-state">첫 보고서를 준비하고 있습니다.</p>')
    else:
        body.append('<div class="archive-list">')
        for issue in reversed(issues):
            url = "./daily/" + issue["date"] + "/index.html"
            body.extend(['<article class="archive-card"><p class="eyebrow">' + issue["date"] + "</p>",
                         '<h3><a href="' + url + '">' + escape(issue_title(issue)) + "</a></h3>",
                         "<p>" + escape(issue["summary"][0]) + "</p>",
                         tags_html(sorted({tag for collection in ITEM_COLLECTIONS.values()
                                           for item in issue[collection] for tag in item.get("tags", [])}), "./"),
                         "</article>"])
        body.append("</div>")
    body.append("</section>")
    body.append("<script>" + (ROOT / "search.js").read_text(encoding="utf-8") + "</script>")
    return "\n".join(body)


def build_site(root, output=None):
    template = (root / "template.html").read_text(encoding="utf-8")
    for token in ("@@TITLE@@", "@@BASE@@", "@@CONTENT@@"):
        require(token in template, "Template is missing " + token)
    issues = []
    state = empty_state()
    for path in sorted((root / "reports").glob("*.json")):
        issue = load_json(path)
        require(path.stem == issue["date"], "Report filename/date mismatch")
        validate_issue(issue, state)
        introduce(issue, state)
        if issue["github_snapshot"]:
            state["observations"][issue["date"]] = issue["github_snapshot"]
        issues.append(issue)
    output = output or root / "site"
    output.mkdir(parents=True, exist_ok=True)
    active_dates = {issue["date"] for issue in issues}
    for old_page in (output / "daily").glob("*/index.html"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", old_page.parent.name) and old_page.parent.name not in active_dates:
            old_page.unlink()

    def write_page(path, title, base, body):
        page = template.replace("@@TITLE@@", escape(title)).replace("@@BASE@@", base)
        page = page.replace("@@CONTENT@@", body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8")

    write_page(output / "index.html", "보고서 아카이브", "./", render_home(issues))
    for issue in issues:
        write_page(output / "daily" / issue["date"] / "index.html",
                   issue_title(issue), "../../", render_issue(issue))
    (output / ".nojekyll").touch()
    return len(issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "delivery", "record", "promote", "record-publication", "digest", "record-digest"):
        command = commands.add_parser(name)
        command.add_argument("--date", required=True)
        if name in ("record", "promote", "record-publication"):
            command.add_argument("--digest", required=True)
        if name == "record":
            command.add_argument("--part", required=True, type=int)
        if name == "promote":
            command.add_argument("--approved", required=True, action="store_true",
                                 help="Only use after the user approved this exact public preview")
        if name in ("digest", "record-digest"):
            command.add_argument("--mode", choices=("preview", "published"), required=name == "record-digest")
        if name == "record-digest":
            command.add_argument("--message-digest", required=True)
            command.add_argument("--message-id", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--file", required=True, type=Path)
    revision = commands.add_parser("revise")
    revision.add_argument("--file", required=True, type=Path)
    revision.add_argument("--expected-digest", required=True)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path)
    commands.add_parser("schema")
    args = parser.parse_args()

    if args.command == "context":
        print(json_text(context_for(args.date, load_state(ROOT))), end="")
    elif args.command in ("stage", "revise"):
        issue = load_json(args.file)
        if args.command == "revise":
            revise_issue(ROOT, issue, args.expected_digest)
        else:
            stage_issue(ROOT, issue)
        issue = load_draft(ROOT, issue["date"])
        print(json_text({"date": issue["date"], "revision": issue.get("revision", 1),
                         "digest": issue_digest(issue), "status": "prepared"}), end="")
    elif args.command == "build":
        print(json_text({"approved_issues": build_site(ROOT, args.output)}), end="")
    elif args.command == "schema":
        print((ROOT / "issue-schema.json").read_text(encoding="utf-8"), end="")
    elif args.command == "record-publication":
        record_publication(ROOT, args.date, args.digest)
        print(json_text({"status": "publication_recorded", "date": args.date}), end="")
    elif args.command == "digest":
        print(json_text(digest_payload(ROOT, args.date, args.mode)), end="")
    elif args.command == "record-digest":
        payload = digest_payload(ROOT, args.date, args.mode)
        require(not payload["already_sent"], "This digest was already sent")
        require(args.message_digest == payload["message_digest"], "Teams message digest changed")
        issue = load_draft(ROOT, args.date)
        state = record_digest_receipt(issue, load_state(ROOT), args.message_digest,
                                      payload["message"], args.message_id, args.mode)
        save_state(ROOT, state)
        print(json_text({"status": "digest_delivered", "message_id": args.message_id}), end="")
    else:
        issue = load_draft(ROOT, args.date)
        if args.command == "delivery":
            parts = delivery_parts(issue)
            state = load_state(ROOT)
            receipt = state["receipts"].get(delivery_key(issue))
            require(receipt is None or receipt["digest"] == issue_digest(issue), "Stored receipt digest mismatch")
            sent = set(receipt["sent_parts"]) if receipt else set()
            print(json_text({"date": args.date, "revision": issue.get("revision", 1),
                             "digest": issue_digest(issue), "total": len(parts),
                             "pending_parts": [{"index": index, "text": part} for index, part in enumerate(parts)
                                               if index not in sent]}), end="")
        elif args.command == "record":
            state = record_receipt(issue, load_state(ROOT), args.digest, args.part, len(delivery_parts(issue)))
            save_state(ROOT, state)
            print(json_text(state["receipts"][delivery_key(issue)]), end="")
        elif args.command == "promote":
            promote_issue(ROOT, args.date, args.digest)
            print(json_text({"status": "approved_local", "date": args.date,
                             "next": "Build, commit only public files, push, and verify Pages deployment."}), end="")


if __name__ == "__main__":
    main()
