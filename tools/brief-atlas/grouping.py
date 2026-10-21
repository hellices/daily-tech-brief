"""Explainable lexical reading groups; no model, external service, or network."""
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import math
import re
import unicodedata

MIN_SIMILARITY = 0.16
NEIGHBORS = 4
MAX_GROUP_SIZE = 8
STOP_WORDS = frozenset((
    "a an the and or of for to in on with from by as at is are be via its this that how "
    "what when can we our using toward towards based study new approach system systems "
    "paper research results show shows analysis framework method methods proposed propose "
    "api apis sdk cli release releases patch version "
    "논문 연구 제안 제안한다 논문은 기반 위한 통해 대한 이를 기존 새로운 결과 "
    "같은 있는 있다 한다 하는 했으며 위해 대해 또한 대신 직접 경우 이를 위한"
).split())


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s_\-\u2010-\u2015]+", " ", text).strip()


def features(text, broad):
    words = re.findall(r"[a-z][a-z0-9]+|[가-힣]{2,}", normalize(text))
    generic_words = {word for phrase in broad for word in phrase.split()}
    tokens = Counter(word for word in words if word not in STOP_WORDS and word not in generic_words
                     and not re.fullmatch(r"v\d+", word))
    for size in (2, 3):
        for index in range(len(words) - size + 1):
            phrase = words[index:index + size]
            term = " ".join(phrase)
            if (term not in broad and not any(word in STOP_WORDS or re.fullmatch(r"v\d+", word) for word in phrase)
                    and any(word not in generic_words and not re.fullmatch(r"v\d+", word) for word in phrase)):
                tokens[term] += 1
    return tokens


def distinct_terms(weights, limit=5):
    ranked = sorted(weights, key=lambda term: (" " not in term, -weights[term], -len(term.split()), term))
    selected = []
    for term in ranked:
        if any(" " + term + " " in " " + other + " " or " " + other + " " in " " + term + " "
               for other in selected):
            continue
        selected.append(term)
        if len(selected) == limit:
            break
    return selected


def cluster_pairs(count, pairs):
    adjacency = {i: {} for i in range(count)}
    for edge in pairs:
        a, b = edge["source"], edge["target"]
        adjacency[a][b] = edge["score"]
        adjacency[b][a] = edge["score"]
    used, groups = set(), []
    for edge in sorted(pairs, key=lambda e: (-e["score"], e["source"], e["target"])):
        a, b = edge["source"], edge["target"]
        if a in used or b in used:
            continue
        members = [a, b]
        candidates = (set(adjacency[a]) & set(adjacency[b])) - used - set(members)
        while candidates and len(members) < MAX_GROUP_SIZE:
            chosen = min(candidates, key=lambda i: (-min(adjacency[i][j] for j in members), i))
            members.append(chosen)
            candidates &= set(adjacency[chosen])
            candidates -= set(members)
        used.update(members)
        groups.append(sorted(members))
    return groups


def build_article_groups(items, details, tags):
    if len(items) != len(details):
        raise ValueError("Article metadata/evidence length mismatch")
    broad = {normalize(value) for tag in tags
             for value in [tag["id"], tag["label"], *tag.get("aliases", [])]}
    by_identity = defaultdict(list)
    for index, item in enumerate(items):
        by_identity[item["identity"]].append(index)
    articles = []
    for identity, occurrences in sorted(by_identity.items()):
        latest = max(occurrences, key=lambda i: (items[i]["date"], items[i]["id"]))
        item, detail = items[latest], details[latest]
        weights = defaultdict(float)
        naming_terms = set(features(item["title"], broad))
        for topic in detail.get("topics", []):
            naming_terms.update(features(topic, broad))
        fields = [(item["title"], 3.0), *[(topic, 4.0) for topic in detail.get("topics", [])],
                  (detail.get("summary", ""), 0.7)]
        for text, weight in fields:
            for term, frequency in features(text, broad).items():
                weights[term] += weight * (1 + math.log(frequency))
        articles.append({
            "identity": identity, "index": latest, "occurrences": sorted(occurrences),
            "tags": set(item["tags"]), "weights": dict(weights), "naming_terms": naming_terms
        })
    frequencies = Counter(term for article in articles for term in article["weights"])
    for article in articles:
        weighted = {term: tf * (1 + math.log((len(articles) + 1) / (frequencies[term] + 1)))
                    for term, tf in article["weights"].items()}
        norm = math.sqrt(sum(weight * weight for weight in weighted.values()))
        article["vector"] = {term: weight / norm for term, weight in weighted.items()} if norm else {}
    pairs = []
    nearest = defaultdict(list)
    for a, b in combinations(range(len(articles)), 2):
        left, right = articles[a], articles[b]
        if not left["tags"].intersection(right["tags"]):
            continue
        common = left["vector"].keys() & right["vector"].keys()
        naming_common = left["naming_terms"] & right["naming_terms"]
        if len([term for term in naming_common if " " not in term]) < 2 and not any(" " in term for term in naming_common):
            continue
        weights = {term: left["vector"][term] * right["vector"][term] for term in sorted(common)}
        score = sum(weights.values())
        if score < MIN_SIMILARITY:
            continue
        terms = distinct_terms(weights)
        pairs.append({"source": a, "target": b, "score": score, "shared_terms": terms})
        nearest[a].append((score, b))
        nearest[b].append((score, a))
    choices = {index: {other for _, other in sorted(values, key=lambda pair: (-pair[0], pair[1]))[:NEIGHBORS]}
               for index, values in nearest.items()}
    pairs = [edge for edge in pairs
             if edge["target"] in choices[edge["source"]] and edge["source"] in choices[edge["target"]]]
    edge_lookup = {(edge["source"], edge["target"]): edge for edge in pairs}
    groups, grouped_indices = [], set()
    for members in cluster_pairs(len(articles), pairs):
        member_articles = [articles[i] for i in members]
        source_indices = sorted(index for article in member_articles for index in article["occurrences"])
        shared = Counter()
        links = []
        for a, b in combinations(members, 2):
            edge = edge_lookup[a, b]
            for term in edge["shared_terms"]:
                shared[term] += edge["score"]
            links.append({
                "source": articles[a]["index"], "target": articles[b]["index"],
                "score": round(edge["score"], 6), "shared_terms": edge["shared_terms"],
                "shared_tags": sorted(articles[a]["tags"] & articles[b]["tags"])
            })
        naming_counts = Counter(term for article in member_articles for term in article["naming_terms"])
        label_weights = {term: weight for term, weight in shared.items() if naming_counts[term] >= 2}
        terms = distinct_terms(label_weights or shared)
        anchor = min(member_articles, key=lambda a: (
            min(items[i]["date"] for i in a["occurrences"]), a["identity"]
        ))["identity"]
        identifier = "group-" + hashlib.sha256(anchor.encode("utf-8")).hexdigest()[:16]
        groups.append({
            "id": identifier, "kind": "group", "label": " · ".join(terms[:2]),
            "family": ("research" if any(items[i]["section"] == "papers" for i in source_indices)
                       else "platform" if any(items[i]["section"] == "cncf" for i in source_indices)
                       else "development"),
            "terms": terms, "documents": source_indices, "article_count": len(members),
            "first": min(items[i]["date"] for i in source_indices),
            "last": max(items[i]["date"] for i in source_indices),
            "links": links,
            "representatives": sorted((a["index"] for a in member_articles),
                                      key=lambda i: (items[i]["date"], items[i]["id"]), reverse=True)[:3]
        })
        grouped_indices.update(source_indices)
    return {
        "version": 1, "method": "weighted-tfidf-v1",
        "parameters": {"minimum_cosine": MIN_SIMILARITY, "mutual_neighbors": NEIGHBORS,
                       "maximum_group_size": MAX_GROUP_SIZE, "linkage": "complete"},
        "unique_articles": len(articles),
        "groups": sorted(groups, key=lambda group: group["id"]),
        "ungrouped_documents": [i for i in range(len(items)) if i not in grouped_indices]
    }
