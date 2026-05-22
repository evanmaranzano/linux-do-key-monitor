import re
import base64
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

    # 1. 直接 regex 匹配
    for kp in key_patterns:
        matches = re.findall(kp["pattern"], html_content)
        for m in matches:
            results.append((m, kp["name"]))

    # 2. base64 编码的 key
    b64_pattern = r'[A-Za-z0-9+/]{40,}={0,2}'
    b64_matches = re.findall(b64_pattern, html_content)
    for b64_str in b64_matches:
        try:
            decoded = base64.b64decode(b64_str).decode('utf-8')
            for kp in key_patterns:
                if re.fullmatch(kp["pattern"], decoded):
                    results.append((decoded, kp["name"]))
        except Exception:
            continue

    # 去重
    seen = set()
    unique = []
    for item in results:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


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
