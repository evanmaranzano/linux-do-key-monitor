import time
import unittest

import extractor
import monitor


class _Resp:
    def __init__(self, status: int):
        self.status = status


class PerformanceTest(unittest.TestCase):
    def test_verify_key_checks_regions_concurrently_with_2x_speedup(self):
        original_get = extractor.Fetcher.get
        calls = []

        def fake_get(url, headers=None, timeout=10):
            calls.append((url, headers, timeout))
            time.sleep(0.08)
            if url.endswith("/ok"):
                return _Resp(200)
            return _Resp(401)

        def serial_verify(key_value, regions, verify_type="bearer"):
            saw_auth_fail = False
            for region in regions:
                headers = {}
                if verify_type == "bearer":
                    headers["Authorization"] = f"Bearer {key_value}"
                resp = extractor.Fetcher.get(region["verify_url"], headers=headers, timeout=10)
                if resp.status == 200:
                    return 1, region
                if resp.status in (401, 403):
                    saw_auth_fail = True
            return (0, None) if saw_auth_fail else (-1, None)

        regions = [
            {"name": "bad-1", "verify_url": "https://example.test/bad-1"},
            {"name": "bad-2", "verify_url": "https://example.test/bad-2"},
            {"name": "ok", "verify_url": "https://example.test/ok"},
            {"name": "bad-3", "verify_url": "https://example.test/bad-3"},
        ]

        try:
            extractor.Fetcher.get = fake_get
            started = time.perf_counter()
            serial_valid, serial_region = serial_verify("secret", regions)
            serial_elapsed = time.perf_counter() - started

            calls.clear()
            started = time.perf_counter()
            valid, matched_region = extractor.verify_key("secret", regions)
            elapsed = time.perf_counter() - started
        finally:
            extractor.Fetcher.get = original_get

        self.assertEqual(serial_valid, 1)
        self.assertEqual(serial_region["name"], "ok")
        self.assertEqual(valid, 1)
        self.assertEqual(matched_region["name"], "ok")
        self.assertEqual(len(calls), 4)
        self.assertGreaterEqual(serial_elapsed / elapsed, 2.0)

    def test_fetch_topic_details_fetches_matching_topics_with_2x_speedup(self):
        class FakeFetcher:
            def fetch_topic_detail(self, tid):
                time.sleep(0.10)
                return {"id": tid}

        topics = [{"id": i} for i in range(4)]
        fetcher = FakeFetcher()

        started = time.perf_counter()
        serial_details = {t["id"]: fetcher.fetch_topic_detail(t["id"]) for t in topics}
        serial_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        details = monitor.fetch_topic_details(fetcher, topics)
        elapsed = time.perf_counter() - started

        self.assertEqual(set(serial_details), {0, 1, 2, 3})
        self.assertEqual(set(details), {0, 1, 2, 3})
        self.assertGreaterEqual(serial_elapsed / elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
