import importlib.util
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError


MODULE_PATH = Path(__file__).resolve().parents[1] / "feed_fetch.py"
FEED = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title><entry><title>Item</title></entry></feed>'
URL = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=week"


class FeedTests(unittest.TestCase):
    def api(self):
        self.assertTrue(MODULE_PATH.exists(), "Bounded feed retry helper is not implemented")
        spec = importlib.util.spec_from_file_location("feed_fetch", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_retry_after_seconds_date_and_default_backoff(self):
        b = self.api()
        now = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(b.retry_delay("60", 0, now), 60)
        self.assertEqual(b.retry_delay("Wed, 16 Sep 2026 05:01:30 GMT", 0, now), 90)
        self.assertEqual(b.retry_delay(None, 0, now), 60)
        self.assertEqual(b.retry_delay(None, 1, now), 120)

    def test_429_waits_then_retries_and_caches_success(self):
        b = self.api()
        attempts, sleeps = [], []
        def request(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise HTTPError(url, 429, "rate limited", {"Retry-After": "60"}, None)
            return FEED
        with tempfile.TemporaryDirectory() as folder:
            result = b.fetch_feed(URL, Path(folder), "2026-09-16", request=request, sleep=sleeps.append)
            self.assertEqual(sleeps, [60])
            self.assertEqual(len(attempts), 2)
            self.assertTrue(Path(result["path"]).exists())
            cached = b.fetch_feed(URL, Path(folder), "2026-09-16", request=request, sleep=sleeps.append)
            self.assertTrue(cached["cached"])
            self.assertEqual(len(attempts), 2)

    def test_long_retry_after_defers_instead_of_retrying_early(self):
        b = self.api()
        def request(url):
            raise HTTPError(url, 429, "rate limited", {"Retry-After": "900"}, None)
        with tempfile.TemporaryDirectory() as folder:
            sleeps = []
            with self.assertRaisesRegex(ValueError, "deferred"):
                b.fetch_feed(URL, Path(folder), "2026-09-16", request=request, sleep=sleeps.append)
            self.assertEqual(sleeps, [])

    def test_403_and_invalid_documents_are_not_retried_or_cached(self):
        b = self.api()
        def denied(url):
            raise HTTPError(url, 403, "forbidden", {}, None)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(HTTPError):
                b.fetch_feed(URL, Path(folder), "2026-09-16", request=denied)
            with self.assertRaisesRegex(ValueError, "feed"):
                b.fetch_feed(URL, Path(folder), "2026-09-16", request=lambda url: b"<html>blocked</html>")
            self.assertEqual(list(Path(folder).glob("*.xml")), [])

    def test_retry_count_is_bounded(self):
        b = self.api()
        calls, sleeps = [], []
        def request(url):
            calls.append(url)
            raise HTTPError(url, 429, "rate limited", {}, None)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(HTTPError):
                b.fetch_feed(URL, Path(folder), "2026-09-16", request=request, sleep=sleeps.append)
            self.assertEqual(len(calls), 3)
            self.assertEqual(sleeps, [60, 120])


if __name__ == "__main__":
    unittest.main()
