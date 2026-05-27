from scrapling.fetchers import Fetcher


class DiscourseFetcher:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _get_json(self, url: str) -> dict | None:
        try:
            resp = Fetcher.get(url, timeout=30, headers={"Referer": self.base_url})
            return resp.json()
        except Exception as e:
            print(f"[!] 请求失败 {url}: {e}")
            return None

    def fetch_category_topics(self, category_slug: str, category_id: int, max_pages: int = 3) -> list[dict]:
        topics = []
        for page in range(max_pages):
            url = f"{self.base_url}/c/{category_slug}/{category_id}.json?page={page}"
            data = self._get_json(url)
            if not data or "topic_list" not in data:
                break
            batch = data["topic_list"].get("topics", [])
            if not batch:
                break
            topics.extend(batch)
        return topics

    def fetch_topic_detail(self, topic_id: int) -> dict | None:
        url = f"{self.base_url}/t/topic/{topic_id}.json"
        return self._get_json(url)

    def close(self):
        pass
