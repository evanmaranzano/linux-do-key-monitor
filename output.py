import json
from datetime import datetime
from pathlib import Path


def log_new_key(key_value: str, key_type: str, valid: int, topic_id: int, base_url: str):
    ts = datetime.now().strftime("%H:%M:%S")
    short = f"{key_value[:8]}...{key_value[-6:]}"
    status = "有效 ✓" if valid == 1 else ("无效 ✗" if valid == 0 else "未知 ?")
    source = f"/t/topic/{topic_id}"
    print(f"[{ts}] 发现新key! {key_type} | {short} | {status} | 来源: {source}")


def log_round_summary(scanned: int, matched: int, found: int, valid: int):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 本轮完成: 扫描 {scanned} 帖, 命中 {matched} 帖, 新发现 {found} key, 有效 {valid}")


def log_poll_start(round_num: int):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 开始第 {round_num} 轮轮询...")


def log_error(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [!] {msg}")


def write_json(keys: list[dict], json_path: str, base_url: str):
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    records = []
    for k in keys:
        records.append({
            "key": k["key"],
            "type": k["type"],
            "valid": k["valid"],
            "topic_url": f"{base_url}/t/topic/{k['topic_id']}",
            "verified_at": k["verified_at"],
            "discovered_at": k["discovered_at"],
        })
    tmp = Path(json_path).with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(json_path)
