import argparse
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from fetcher import DiscourseFetcher
from extractor import filter_by_title, extract_keys, verify_key
from store import Store
from switcher import create_switch, cleanup_expired_providers
import output


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def handle_cc_switch(cfg: dict, key_value: str, base_url: str) -> bool:
    sw = cfg.get("cc_switch", {})
    if not sw.get("enabled"):
        return True
    return create_switch(sw["db_path"], key_value, sw.get("key_type", "mimo"), base_url)


def fetch_topic_details(fetcher: DiscourseFetcher, topics: list[dict]) -> dict[int, dict | None]:
    if not topics:
        return {}
    if len(topics) == 1:
        tid = topics[0]["id"]
        try:
            return {tid: fetcher.fetch_topic_detail(tid)}
        except Exception as e:
            output.log_error(f"获取帖子详情失败 {tid}: {e}")
            return {tid: None}

    details = {}
    max_workers = min(len(topics), 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_tid = {
            executor.submit(fetcher.fetch_topic_detail, t["id"]): t["id"]
            for t in topics
        }
        for future in as_completed(future_to_tid):
            tid = future_to_tid[future]
            try:
                details[tid] = future.result()
            except Exception as e:
                output.log_error(f"获取帖子详情失败 {tid}: {e}")
                details[tid] = None
    return details


def run_one_round(cfg: dict, fetcher: DiscourseFetcher, store: Store, round_num: int):
    base_url = cfg["forum"]["base_url"]
    cat_slug = cfg["forum"]["category_slug"]
    cat_id = cfg["forum"]["category_id"]
    max_pages = cfg["monitor"]["max_pages"]
    keywords = cfg["filter"]["keywords"]
    exclude_kw = cfg["filter"]["exclude_keywords"]
    key_patterns = cfg["keys"]
    json_path = cfg["output"]["json_path"]

    output.log_poll_start(round_num)

    # 补写失败的 CC Switch
    for pending in store.get_pending_cc_switches():
        try:
            if handle_cc_switch(cfg, pending["key_value"], pending["base_url"]):
                store.mark_cc_switch_done(pending["key_value"])
        except Exception as e:
            output.log_error(f"CC Switch 补写失败 {pending['key_value'][:12]}...: {e}")

    # 重新验证 valid=-1 的 key
    for rk in store.get_keys_needing_reverify():
        key_cfg = next((k for k in key_patterns if k["name"] == rk["key_type"]), None)
        if not key_cfg:
            continue
        regions = key_cfg.get("regions", [{"name": "", "verify_url": key_cfg["verify_url"]}])
        valid, matched_region = verify_key(rk["key_value"], regions, key_cfg.get("verify_type", "bearer"))
        store.update_key_validity(rk["key_value"], valid)
        store.increment_reverify_count(rk["key_value"])
        if valid == 1:
            region_name = matched_region["name"] if matched_region else ""
            key_base_url = matched_region.get("base_url", "") if matched_region else ""
            output.log_new_key(rk["key_value"], rk["key_type"], valid, 0, base_url, region_name)
            if handle_cc_switch(cfg, rk["key_value"], key_base_url):
                store.mark_cc_switch_done(rk["key_value"])

    topics = fetcher.fetch_category_topics(cat_slug, cat_id, max_pages)
    if not topics:
        output.log_error("未能获取帖子列表")
        return

    seen_ids = set()
    for t in topics:
        tid = t.get("id")
        if store.is_topic_seen(tid):
            seen_ids.add(tid)

    matched = filter_by_title(topics, keywords, exclude_kw, seen_ids)
    new_keys_found = 0
    valid_count = 0
    details_by_id = fetch_topic_details(fetcher, matched)

    for t in matched:
        tid = t["id"]
        detail = details_by_id.get(tid)
        if not detail or "post_stream" not in detail:
            continue

        posts = detail["post_stream"].get("posts", [])
        if not posts:
            continue

        html = posts[0].get("cooked", "")
        found = extract_keys(html, key_patterns)

        if not found:
            store.mark_topic_seen(tid, t.get("title", ""), has_key=False)
            continue

        for key_value, key_type in found:
            if store.is_key_known(key_value):
                continue

            key_cfg = next((k for k in key_patterns if k["name"] == key_type), None)
            valid = -1
            region_name = ""
            key_base_url = ""
            if key_cfg and "regions" in key_cfg:
                valid, matched_region = verify_key(key_value, key_cfg["regions"], key_cfg.get("verify_type", "bearer"))
                if matched_region:
                    region_name = matched_region["name"]
                    key_base_url = matched_region.get("base_url", "")
            elif key_cfg:
                # 兼容旧配置（单 verify_url）
                regions = [{"name": "", "verify_url": key_cfg["verify_url"]}]
                valid, _ = verify_key(key_value, regions, key_cfg.get("verify_type", "bearer"))

            store.save_key(key_value, key_type, tid, valid, region_name, key_base_url)
            output.log_new_key(key_value, key_type, valid, tid, base_url, region_name)
            new_keys_found += 1
            if valid == 1:
                valid_count += 1
                if handle_cc_switch(cfg, key_value, key_base_url):
                    store.mark_cc_switch_done(key_value)

        store.mark_topic_seen(tid, t.get("title", ""), has_key=True)

    all_keys = store.get_valid_keys()
    try:
        output.write_json(all_keys, json_path, base_url)
    except Exception as e:
        output.log_error(f"写入 JSON 失败: {e}")

    output.log_round_summary(len(topics), len(matched), new_keys_found, valid_count)


def main():
    parser = argparse.ArgumentParser(description="linux.do API Key Monitor")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"配置文件不存在: {cfg_path}")
        return

    cfg = load_config(str(cfg_path))
    interval = cfg["monitor"]["interval"]
    base_url = cfg["forum"]["base_url"]

    print("=== linux.do Key Monitor ===")
    print(f"论坛: {base_url}")
    print(f"轮询间隔: {interval}s")
    print(f"关键词: {', '.join(cfg['filter']['keywords'])}")
    for k in cfg["keys"]:
        regions = [r["name"] for r in k.get("regions", [])]
        region_str = ", ".join(regions) if regions else "单端点"
        print(f"Key 模式: {k['name']} ({region_str})")
    cc_sw = cfg.get("cc_switch", {})
    if cc_sw.get("enabled"):
        print(f"CC Switch: 启用")
    print()

    store = Store(cfg["output"]["db_path"])
    fetcher = DiscourseFetcher(base_url)

    running = True

    def on_signal(sig, frame):
        nonlocal running
        print("\n收到退出信号，正在停止...")
        running = False

    signal.signal(signal.SIGINT, on_signal)

    round_num = 1
    try:
        while running:
            try:
                run_one_round(cfg, fetcher, store, round_num)
            except Exception as e:
                output.log_error(f"轮询异常: {e}")

            # 每 5 轮清理一次 monitor 创建的失效 provider
            if round_num % 5 == 0:
                sw = cfg.get("cc_switch", {})
                if sw.get("enabled"):
                    try:
                        cleanup_expired_providers(sw["db_path"])
                    except Exception as e:
                        output.log_error(f"CC Switch 清理失败: {e}")

            round_num += 1

            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)
    finally:
        store.close()
        print("已停止。")


if __name__ == "__main__":
    main()
