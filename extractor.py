import re
from scrapling.fetchers import Fetcher


def filter_by_title(
    topics: list[dict],
    keywords: list[str],
    exclude_keywords: list[str],
    seen_ids: set[int],
) -> list[dict]:
    result = []
    for t in topics:
        tid = t.get("id")
        if tid in seen_ids:
            continue
        title = (t.get("title") or "").lower()
        if any(ex.lower() in title for ex in exclude_keywords):
            continue
        if any(kw.lower() in title for kw in keywords):
            result.append(t)
    return result


def extract_keys(html_content: str, key_patterns: list[dict]) -> list[tuple[str, str]]:
    results = []
    for kp in key_patterns:
        matches = re.findall(kp["pattern"], html_content)
        for m in matches:
            results.append((m, kp["name"]))
    return results


def verify_key(key_value: str, verify_url: str, verify_type: str = "bearer") -> int:
    try:
        fetcher = Fetcher(auto_match=False)
        headers = {}
        if verify_type == "bearer":
            headers["Authorization"] = f"Bearer {key_value}"
        resp = fetcher.get(verify_url, headers=headers, timeout=10)
        if resp.status == 200:
            return 1
        elif resp.status in (401, 403):
            return 0
        return -1
    except Exception:
        return -1
