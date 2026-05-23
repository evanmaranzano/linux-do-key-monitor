import logging
import re
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def _extract_inserted_keys(html_content: str, key_patterns: list[dict]) -> list[tuple[str, str]]:
    """识别 key 中间被插入文字的情况，如 tp-xxx请删除此处yyy"""
    results = []
    for kp in key_patterns:
        pat = kp["pattern"]
        # 提取前缀（如 tp-）
        prefix_m = re.match(r'^([a-zA-Z][a-zA-Z0-9_-]*)', pat)
        if not prefix_m:
            continue
        prefix = prefix_m.group(1)
        # 找所有 前缀+非空白字符，只在包含非 ASCII 时处理
        for m in re.finditer(re.escape(prefix) + r'[\S]+', html_content):
            raw = m.group(0)
            if not re.search(r'[^\x00-\x7f]', raw):
                continue
            cleaned = re.sub(r'[^\x00-\x7f]', '', raw)
            if re.fullmatch(pat, cleaned):
                results.append((cleaned, kp["name"]))
    return results


def extract_keys(html_content: str, key_patterns: list[dict]) -> list[tuple[str, str]]:
    results = []

    # 1. 直接 regex 匹配
    for kp in key_patterns:
        matches = re.findall(kp["pattern"], html_content)
        for m in matches:
            results.append((m, kp["name"]))

    # 2. key 中间被插入文字（如中文）
    results.extend(_extract_inserted_keys(html_content, key_patterns))

    # 3. base64 编码的 key
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


_logger = logging.getLogger(__name__)


def _verify_region(key_value: str, region: dict, verify_type: str) -> tuple[int, dict | None]:
    try:
        headers = {}
        if verify_type == "bearer":
            headers["Authorization"] = f"Bearer {key_value}"
        resp = Fetcher.get(region["verify_url"], headers=headers, timeout=10)
        if resp.status == 200:
            return 1, region
        if resp.status in (401, 403):
            return 0, None
    except Exception as e:
        _logger.debug("验证区域 %s 失败: %s", region.get("name", "?"), e)
    return -1, None


def verify_key(key_value: str, regions: list[dict], verify_type: str = "bearer") -> tuple[int, dict | None]:
    """遍历所有区域验证 key，返回 (valid, matched_region)。"""
    if not regions:
        return -1, None
    if len(regions) == 1:
        return _verify_region(key_value, regions[0], verify_type)

    saw_auth_fail = False
    max_workers = min(len(regions), 4)
    results: dict[int, tuple[int, dict | None]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_verify_region, key_value, region, verify_type): i
            for i, region in enumerate(regions)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = (-1, None)
            if results[idx][0] == 1:
                return 1, results[idx][1]

    for i in range(len(regions)):
        valid, matched_region = results[i]
        if valid == 1:
            return 1, matched_region
        if valid == 0:
            saw_auth_fail = True
    return (0, None) if saw_auth_fail else (-1, None)
