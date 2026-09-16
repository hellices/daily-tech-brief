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
    require(isinstance(issue, dict) and issue.get("schema_version") == 1, "Invalid issue schema")
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
              "discussions": (7, "discussion", "community"), "cncf": (5, "change", "cncf")}
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
        for field in ("title", "summary", "significance", "caveat"):
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


def stage_issue(root, issue):
    state = load_state(root)
    issue = copy.deepcopy(issue)
    for name in ITEM_COLLECTIONS.values():
        for item in issue.get(name, []):
            require("tags" in item, "New items require tags from tags.json")
            item["tags"] = normalize_tags(item["tags"])
    comparison = context_for(issue["date"], state)["previous_snapshot"]
    if comparison is not None and "github_previous_snapshot" not in issue:
        issue["github_previous_snapshot"] = comparison
    validate_issue(issue, state)
    receipt = state["receipts"].get(issue["date"])
    require(receipt is None or receipt["digest"] == issue_digest(issue),
            "Cannot rewrite an issue after delivery has started")
    published = root / "reports" / (issue["date"] + ".json")
    require(not published.exists() or issue_digest(load_json(published)) == issue_digest(issue),
            "Cannot rewrite an already published issue")
    atomic_json(root / ".local" / "drafts" / (issue["date"] + ".json"), issue)
    if issue["github_snapshot"] is not None:
        state["observations"][issue["date"]] = issue["github_snapshot"]
    save_state(root, state)


def load_draft(root, day):
    iso_day(day)
    path = root / ".local" / "drafts" / (day + ".json")
    require(path.exists(), "No prepared report for " + day + "; do not send yesterday's issue")
    issue = load_json(path)
    require(issue["date"] == day, "Draft filename/date mismatch")
    validate_issue(issue, load_state(root))
    return issue


def report_text(issue):
    lines = ["Daily Tech Brief | " + issue["date"] + " (KST)", issue["headline"], "",
             "오늘의 세 줄", *["• " + line for line in issue["summary"]], ""]
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
    return ["Daily Tech Brief " + issue["date"] + " [" + str(index + 1) + "/" + str(len(chunks)) + "]\n\n" + part
            for index, part in enumerate(chunks)]


def record_receipt(issue, state, digest, part, total):
    require(digest == issue_digest(issue), "Receipt digest mismatch")
    require(total == len(delivery_parts(issue)), "Delivery part count mismatch")
    require(type(part) is int and 0 <= part < total, "Invalid delivery part index")
    result = copy.deepcopy(state)
    previous = result["receipts"].get(issue["date"])
    require(previous is None or (previous["digest"] == digest and previous["total"] == total),
            "Conflicting delivery receipt")
    receipt = previous or {"digest": digest, "total": total, "sent_parts": []}
    receipt["sent_parts"] = sorted(set(receipt["sent_parts"] + [part]))
    receipt["complete"] = len(receipt["sent_parts"]) == total
    result["receipts"][issue["date"]] = receipt
    if receipt["complete"]:
        introduce(issue, result)
    return result


def promote_issue(root, day, digest):
    issue = load_draft(root, day)
    require(issue_digest(issue) == digest, "Approved digest does not match current draft")
    target = root / "reports" / (day + ".json")
    require(not target.exists() or issue_digest(load_json(target)) == digest,
            "A different issue is already public for this date")
    atomic_json(target, issue)


def record_publication(root, day, digest):
    iso_day(day)
    issue = load_json(root / "reports" / (day + ".json"))
    require(issue["date"] == day and issue_digest(issue) == digest, "Publication digest mismatch")
    state = load_state(root)
    validate_issue(issue, state)
    introduce(issue, state)
    save_state(root, state)


def link(url, label):
    return '<a href="' + escape(safe_url(url), quote=True) + '" target="_blank" rel="noopener noreferrer">' + escape(label) + "</a>"


def fields_html(item, fields):
    return "<dl>" + "".join('<dt class="field-label">' + escape(label) + "</dt><dd>"
                           + escape(item[key]) + "</dd>" for key, label in fields) + "</dl>"


def sources_html(item):
    return '<p class="source-links">출처: ' + " · ".join(
        link(url, urlsplit(url).hostname or "원문") for url in dict.fromkeys(item["sources"])) + "</p>"


def issue_title(issue):
    return issue["date"] + " · " + issue["headline"]


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
                items.append({
                    "id": issue["date"] + ":" + anchor, "date": issue["date"],
                    "section": section, "section_label": SECTION_LABELS[section],
                    "title": title, "issue_title": issue_title(issue),
                    "summary": item.get("abstract_summary", item.get("summary", "")), "body": body,
                    "search_text": " ".join([issue["date"], issue["headline"], title, body, item["url"],
                                             SECTION_LABELS[section], terms, *item.get("topics", []),
                                             *issue["summary"], issue["coverage"][section]["note"]]),
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
        '<ul class="summary-list">' + "".join("<li>" + escape(line) + "</li>" for line in issue["summary"]) + "</ul>",
        '<nav class="section-nav" aria-label="보고서 목차"><a href="#github">GitHub</a>'
        '<a href="#papers">AI 논문</a><a href="#community">커뮤니티</a><a href="#cncf">CNCF</a></nav>',
    ]
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
        result.extend(['<section id="' + section + '"><h2>' + heading + "</h2>",
                       '<p class="coverage-note">' + escape(issue["coverage"][section]["note"]) + "</p>"])
        if not issue[name]:
            result.append('<p class="notice">이번 호에는 조건을 충족하는 신규 항목이 없습니다.</p>')
        for index, item in enumerate(issue[name], 1):
            title = item.get("title", item.get("repository", ""))
            result.extend(['<article class="article-item" id="' + item_anchor(section, item)
                           + '"><div class="item-heading">',
                           '<span class="item-number">' + str(index).zfill(2) + "</span>",
                           "<h3>" + link(item["url"], title) + "</h3></div>"])
            result.append(tags_html(item.get("tags", []), "../../"))
            if name == "repositories":
                labels = {"first_observed": "첫 관측", "new_entry": "신규 진입", "first_introduction": "첫 소개"}
                badge = labels.get(item.get("novelty"), "첫 소개")
                result.append('<p class="meta"><span class="badge">' + badge + "</span> 주간 Trending "
                              + str(item["rank"]) + "위</p>")
            if name == "papers":
                evidence = "본문 확인" if item["evidence"] == "full_text" else "초록만 확인 · 상세 검증 제한"
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
    for name in ("context", "delivery", "record", "promote", "record-publication"):
        command = commands.add_parser(name)
        command.add_argument("--date", required=True)
        if name in ("record", "promote", "record-publication"):
            command.add_argument("--digest", required=True)
        if name == "record":
            command.add_argument("--part", required=True, type=int)
        if name == "promote":
            command.add_argument("--approved", required=True, action="store_true",
                                 help="Only use after the user approved this exact public preview")
    stage = commands.add_parser("stage")
    stage.add_argument("--file", required=True, type=Path)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path)
    commands.add_parser("schema")
    args = parser.parse_args()

    if args.command == "context":
        print(json_text(context_for(args.date, load_state(ROOT))), end="")
    elif args.command == "stage":
        issue = load_json(args.file)
        stage_issue(ROOT, issue)
        issue = load_draft(ROOT, issue["date"])
        print(json_text({"date": issue["date"], "digest": issue_digest(issue), "status": "prepared"}), end="")
    elif args.command == "build":
        print(json_text({"approved_issues": build_site(ROOT, args.output)}), end="")
    elif args.command == "schema":
        print((ROOT / "issue-schema.json").read_text(encoding="utf-8"), end="")
    elif args.command == "record-publication":
        record_publication(ROOT, args.date, args.digest)
        print(json_text({"status": "publication_recorded", "date": args.date}), end="")
    else:
        issue = load_draft(ROOT, args.date)
        if args.command == "delivery":
            parts = delivery_parts(issue)
            state = load_state(ROOT)
            receipt = state["receipts"].get(args.date)
            require(receipt is None or receipt["digest"] == issue_digest(issue), "Stored receipt digest mismatch")
            sent = set(receipt["sent_parts"]) if receipt else set()
            print(json_text({"date": args.date, "digest": issue_digest(issue), "total": len(parts),
                             "pending_parts": [{"index": index, "text": part} for index, part in enumerate(parts)
                                               if index not in sent]}), end="")
        elif args.command == "record":
            state = record_receipt(issue, load_state(ROOT), args.digest, args.part, len(delivery_parts(issue)))
            save_state(ROOT, state)
            print(json_text(state["receipts"][args.date]), end="")
        elif args.command == "promote":
            promote_issue(ROOT, args.date, args.digest)
            print(json_text({"status": "approved_local", "date": args.date,
                             "next": "Build, commit only public files, push, and verify Pages deployment."}), end="")


if __name__ == "__main__":
    main()
