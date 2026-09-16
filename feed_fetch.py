#!/usr/bin/env python3
"""Fetch official public feeds with bounded, server-directed retry and caching."""

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen
import xml.etree.ElementTree as ET


MAX_BYTES = 2 * 1024 * 1024
MAX_WAIT = 300


def retry_delay(value, attempt, now):
    if value is None:
        return 60 * (2 ** attempt)
    if value.strip().isdigit():
        return max(1, int(value))
    try:
        target = parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Invalid Retry-After header; defer for manual inspection") from error
    if target.tzinfo is None:
        raise ValueError("Retry-After date must include a timezone")
    return max(1, math.ceil((target - now).total_seconds()))


def request_feed(url):
    with urlopen(url, timeout=30) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Public feed exceeds the bounded download size")
    return content


def validate_feed(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError("Response is not a valid XML feed") from error
    if root.tag not in ("rss", "{http://www.w3.org/2005/Atom}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
        raise ValueError("Response is not an RSS or Atom feed")


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        output.write(content)
        temporary = Path(output.name)
    temporary.replace(path)


def fetch_feed(url, cache_dir, day, request=request_feed, sleep=time.sleep):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ("news.hada.io", "www.reddit.com", "reddit.com"):
        raise ValueError("Use an official HTTPS GeekNews or Reddit feed URL")
    if parsed.username or parsed.password or any(ord(char) < 33 for char in url):
        raise ValueError("Unsafe feed URL")
    datetime.strptime(day, "%Y-%m-%d")
    cache_dir = Path(cache_dir)
    name = day + "-" + hashlib.sha256(url.encode()).hexdigest()[:16]
    path = cache_dir / (name + ".xml")
    log_path = cache_dir / (name + ".json")
    if path.exists():
        validate_feed(path.read_bytes())
        return {"path": str(path), "cached": True, "url": url}
    attempts = []
    waited = 0
    for attempt in range(3):
        try:
            content = request(url)
        except HTTPError as error:
            retry_after = error.headers.get("Retry-After")
            attempts.append({"status": error.code, "retry_after": retry_after,
                             "at": datetime.now(timezone.utc).isoformat()})
            atomic_write(log_path, json.dumps({"url": url, "attempts": attempts}, indent=2).encode())
            if error.code != 429 or attempt == 2:
                raise
            delay = retry_delay(retry_after, attempt, datetime.now(timezone.utc))
            if waited + delay > MAX_WAIT:
                raise ValueError("Feed retry deferred; server Retry-After exceeds this run's wait budget") from error
            if error.fp is not None:
                error.close()
            sleep(delay)
            waited += delay
            continue
        validate_feed(content)
        atomic_write(path, content)
        attempts.append({"status": 200, "at": datetime.now(timezone.utc).isoformat()})
        atomic_write(log_path, json.dumps({"url": url, "attempts": attempts}, indent=2).encode())
        return {"path": str(path), "cached": False, "url": url}
    raise RuntimeError("Feed retry limit exhausted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).resolve().parent / ".local/research/feeds")
    args = parser.parse_args()
    print(json.dumps(fetch_feed(args.url, args.cache_dir, args.date), ensure_ascii=False, indent=2))
