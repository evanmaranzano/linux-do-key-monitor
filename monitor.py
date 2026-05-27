import argparse
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from datetime import datetime

from fetcher import DiscourseFetcher
from extractor import filter_by_title, extract_keys, verify_key
from store import Store
from switcher import create_switch, cleanup_expired_providers
from ccx_sync import add_key_to_ccx, remove_key_from_ccx, get_ccx_keys
from security import is_safe_url
import output

_ccx_proc = None


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_config(cfg: dict) -> list[str]:
    """启动时校验配置安全性，返回警告列表。"""
    warnings = []
    # 校验 forum.base_url
    forum_url = cfg.get("forum", {}).get("base_url", "")
    if forum_url and not is_safe_url(forum_url):
        warnings.append(f"forum.base_url 指向内网: {forum_url}")
    # 校验 key regions 的 URL
    for k in cfg.get("keys", []):
        for r in k.get("regions", []):
            for url_key in ("verify_url", "base_url"):
                url = r.get(url_key, "")
                if url and not is_safe_url(url):
                    warnings.append(f"key '{k['name']}' region '{r['name']}' {url_key} 指向内网: {url}")
    # 校验路径不包含 ..
    for path_key, path_val in [
        ("cc_switch.db_path", cfg.get("cc_switch", {}).get("db_path", "")),
        ("ccx_sync.config_path", cfg.get("ccx_sync", {}).get("config_path", "")),
        ("ccx_sync.exe_path", cfg.get("ccx_sync", {}).get("exe_path", "")),
        ("output.db_path", cfg.get("output", {}).get("db_path", "")),
        ("output.json_path", cfg.get("output", {}).get("json_path", "")),
    ]:
        if path_val and ".." in str(path_val):
            warnings.append(f"{path_key} 包含 .. 路径穿越: {path_val}")
    # 校验 exe_path 存在性
    exe_path = cfg.get("ccx_sync", {}).get("exe_path", "")
    if exe_path and not Path(exe_path).exists():
        warnings.append(f"ccx_sync.exe_path 不存在: {exe_path}")
    return warnings


def handle_cc_switch(cfg: dict, key_value: str, base_url: str) -> bool:
    sw = cfg.get("cc_switch", {})
    if not sw.get("enabled"):
        return True
    return create_switch(sw["db_path"], key_value, sw.get("key_type", "mimo"), base_url)


def restart_ccx(ccx_cfg: dict):
    global _ccx_proc
    exe_path = ccx_cfg.get("exe_path")
    if not exe_path or not Path(exe_path).exists():
        return
    exe_name = Path(exe_path).name
    # 终止已有进程：优先用 PID，回退到 taskkill
    if _ccx_proc is not None:
        try:
            _ccx_proc.terminate()
            _ccx_proc.wait(timeout=5)
        except Exception:
            try:
                _ccx_proc.kill()
            except Exception:
                pass
        _ccx_proc = None
    else:
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True, timeout=5)
            time.sleep(1)
        except Exception:
            pass
    # 后台启动
    try:
        _ccx_proc = subprocess.Popen(
            [exe_path],
            cwd=str(Path(exe_path).parent),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] CCX: 已重启 {exe_name}")
    except Exception as e:
        _ccx_proc = None
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] CCX: 重启失败: {e}")


def reverify_ccx_keys(cfg: dict, store: Store):
    ccx_cfg = cfg.get("ccx_sync", {})
    if not ccx_cfg.get("enabled"):
        return
    config_path = ccx_cfg.get("config_path", "")
    if not config_path:
        return
    ccx_keys = get_ccx_keys(config_path)
    if not ccx_keys:
        return

    key_patterns = cfg["keys"]
    key_type_map = {r["key_value"]: r["key_type"] for r in store.get_all_keys()}
    removed = 0
    for key_value in ccx_keys:
        key_type = key_type_map.get(key_value)
        key_cfg = next((k for k in key_patterns if k["name"] == key_type), None) if key_type else None
        if not key_cfg:
            continue
        regions = key_cfg.get("regions", [])
        cn_region = next((r for r in regions if r["name"] == "cn"), None)
        if not cn_region:
            continue
        valid, _ = verify_key(key_value, [cn_region], key_cfg.get("verify_type", "bearer"))
        if valid == 0:
            remove_key_from_ccx(config_path, key_value)
            store.update_key_validity(key_value, valid)
            removed += 1

    if removed:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] CCX 重新验证: 检查 {len(ccx_keys)} 个, 移除 {removed} 个失效 key")


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

    ccx_cfg = cfg.get("ccx_sync", {})
    ccx_config_path = ccx_cfg.get("config_path", "")
    ccx_mtime_before = Path(ccx_config_path).stat().st_mtime if ccx_config_path and Path(ccx_config_path).exists() else 0

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
        if "regions" in key_cfg:
            regions = key_cfg["regions"]
        else:
            regions = [{"name": "", "verify_url": key_cfg["verify_url"]}]
        valid, matched_region = verify_key(rk["key_value"], regions, key_cfg.get("verify_type", "bearer"))
        store.update_key_validity(rk["key_value"], valid)
        store.increment_reverify_count(rk["key_value"])
        if valid == 1:
            region_name = matched_region["name"] if matched_region else ""
            key_base_url = matched_region.get("base_url", "") if matched_region else ""
            output.log_new_key(rk["key_value"], rk["key_type"], valid, 0, base_url, region_name)
            if handle_cc_switch(cfg, rk["key_value"], key_base_url):
                store.mark_cc_switch_done(rk["key_value"])
            ccx_cfg = cfg.get("ccx_sync", {})
            if ccx_cfg.get("enabled") and region_name == "cn":
                add_key_to_ccx(ccx_cfg["config_path"], rk["key_value"])
            elif ccx_cfg.get("enabled") and region_name != "cn":
                cn_region = next((r for r in key_cfg.get("regions", []) if r["name"] == "cn"), None)
                if cn_region:
                    cn_valid, _ = verify_key(rk["key_value"], [cn_region], key_cfg.get("verify_type", "bearer"))
                    if cn_valid == 1:
                        add_key_to_ccx(ccx_cfg["config_path"], rk["key_value"])
        elif valid == 0:
            ccx_cfg = cfg.get("ccx_sync", {})
            if ccx_cfg.get("enabled"):
                remove_key_from_ccx(ccx_cfg["config_path"], rk["key_value"])

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
            store.mark_topic_seen(tid, t.get("title", ""), has_key=False)
            continue

        found = []
        for post in posts:
            html = post.get("cooked", "")
            found.extend(extract_keys(html, key_patterns))

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
                if region_name == "cn":
                    ccx_cfg = cfg.get("ccx_sync", {})
                    if ccx_cfg.get("enabled"):
                        add_key_to_ccx(ccx_cfg["config_path"], key_value)
                elif region_name != "cn":
                    ccx_cfg = cfg.get("ccx_sync", {})
                    if ccx_cfg.get("enabled"):
                        cn_region = next((r for r in key_cfg.get("regions", []) if r["name"] == "cn"), None)
                        if cn_region:
                            cn_valid, _ = verify_key(key_value, [cn_region], key_cfg.get("verify_type", "bearer"))
                            if cn_valid == 1:
                                add_key_to_ccx(ccx_cfg["config_path"], key_value)

        store.mark_topic_seen(tid, t.get("title", ""), has_key=True)

    all_keys = store.get_valid_keys()
    try:
        output.write_json(all_keys, json_path, base_url)
    except Exception as e:
        output.log_error(f"写入 JSON 失败: {e}")

    output.log_round_summary(len(topics), len(matched), new_keys_found, valid_count)

    if ccx_cfg.get("enabled") and ccx_cfg.get("exe_path"):
        ccx_mtime_after = Path(ccx_config_path).stat().st_mtime if ccx_config_path and Path(ccx_config_path).exists() else 0
        if ccx_mtime_after != ccx_mtime_before:
            restart_ccx(ccx_cfg)


def main():
    parser = argparse.ArgumentParser(description="linux.do API Key Monitor")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"配置文件不存在: {cfg_path}")
        return

    cfg = load_config(str(cfg_path))

    # 启动安全校验
    config_warnings = _validate_config(cfg)
    for w in config_warnings:
        print(f"[!] 安全警告: {w}")
    if any("内网" in w for w in config_warnings):
        print("[!] 检测到内网地址配置，拒绝启动。请检查 config.yaml。")
        return

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
    # 打印验证目标供用户确认
    for k in cfg["keys"]:
        for r in k.get("regions", []):
            for url_key in ("verify_url", "base_url"):
                url = r.get(url_key, "")
                if url:
                    print(f"  验证目标: {url}")
    print()

    store = Store(cfg["output"]["db_path"])
    fetcher = DiscourseFetcher(base_url)

    # 启动时确保 CCX 运行
    ccx_cfg = cfg.get("ccx_sync", {})
    if ccx_cfg.get("enabled") and ccx_cfg.get("exe_path"):
        restart_ccx(ccx_cfg)

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

            # 定期清理失效的 CC Switch provider（每 3 轮）
            if round_num % 3 == 0:
                sw = cfg.get("cc_switch", {})
                if sw.get("enabled"):
                    try:
                        cleanup_expired_providers(sw["db_path"])
                    except Exception as e:
                        output.log_error(f"CC Switch 清理失败: {e}")

            # 定期重新验证 CCX config 中的 key（每 3 轮）
            if round_num % 3 == 0:
                ccx_cfg = cfg.get("ccx_sync", {})
                if ccx_cfg.get("enabled"):
                    try:
                        reverify_ccx_keys(cfg, store)
                    except Exception as e:
                        output.log_error(f"CCX 重新验证失败: {e}")

            round_num += 1

            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)
    finally:
        if _ccx_proc is not None:
            try:
                _ccx_proc.terminate()
                _ccx_proc.wait(timeout=5)
            except Exception:
                try:
                    _ccx_proc.kill()
                except Exception:
                    pass
        store.close()
        print("已停止。")


if __name__ == "__main__":
    main()
