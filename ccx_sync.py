import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CCX: {msg}")


def _read_config(config_path: str) -> dict | None:
    path = Path(config_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"读取配置失败: {e}")
        return None


def _write_config(config_path: str, cfg: dict) -> bool:
    path = Path(config_path)
    for attempt in range(3):
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(path))
            return True
        except Exception as e:
            _log(f"写入配置失败 (attempt {attempt + 1}): {e}")
            if tmp:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    return False


def _find_section_entry(cfg: dict, section: str, provider_name: str = "") -> dict | None:
    """按 name 查找目标 provider，未指定或未找到则回退到 [0]。"""
    entries = cfg.get(section, [])
    if not entries:
        return None
    if provider_name:
        for entry in entries:
            if entry.get("name") == provider_name:
                return entry
    return entries[0]


def _add_key_to_entry(entry: dict, key_value: str) -> bool:
    api_keys = entry.get("apiKeys", [])
    if key_value in api_keys:
        return False
    api_keys.append(key_value)
    entry["apiKeys"] = api_keys
    return True


def add_key_to_ccx(config_path: str, key_value: str,
                   upstream_name: str = "", responses_name: str = "") -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    changed = False
    entry_u = _find_section_entry(cfg, "upstream", upstream_name)
    if entry_u and _add_key_to_entry(entry_u, key_value):
        changed = True
    entry_r = _find_section_entry(cfg, "responsesUpstream", responses_name)
    if entry_r and _add_key_to_entry(entry_r, key_value):
        changed = True

    if changed and _write_config(config_path, cfg):
        count_u = len(entry_u.get("apiKeys", [])) if entry_u else 0
        count_r = len(entry_r.get("apiKeys", [])) if entry_r else 0
        name_u = entry_u.get("name", "?") if entry_u else "-"
        name_r = entry_r.get("name", "?") if entry_r else "-"
        _log(f"添加 key {key_value[:6]}...{key_value[-4:]} (upstream[{name_u}]={count_u}, responses[{name_r}]={count_r})")
        return True
    return False


def _remove_key_from_entry(entry: dict, key_value: str) -> bool:
    api_keys = entry.get("apiKeys", [])
    if key_value not in api_keys:
        return False
    api_keys.remove(key_value)
    entry["apiKeys"] = api_keys
    return True


def remove_key_from_ccx(config_path: str, key_value: str,
                        upstream_name: str = "", responses_name: str = "") -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    changed = False
    entry_u = _find_section_entry(cfg, "upstream", upstream_name)
    if entry_u and _remove_key_from_entry(entry_u, key_value):
        changed = True
    entry_r = _find_section_entry(cfg, "responsesUpstream", responses_name)
    if entry_r and _remove_key_from_entry(entry_r, key_value):
        changed = True

    if changed and _write_config(config_path, cfg):
        count_u = len(entry_u.get("apiKeys", [])) if entry_u else 0
        count_r = len(entry_r.get("apiKeys", [])) if entry_r else 0
        name_u = entry_u.get("name", "?") if entry_u else "-"
        name_r = entry_r.get("name", "?") if entry_r else "-"
        _log(f"移除失效 key {key_value[:6]}...{key_value[-4:]} (upstream[{name_u}]={count_u}, responses[{name_r}]={count_r})")
        return True
    return False


def get_ccx_keys(config_path: str) -> list[str]:
    cfg = _read_config(config_path)
    if cfg is None:
        return []
    result = set()
    for section in ("upstream", "responsesUpstream"):
        for u in cfg.get(section, []):
            result.update(u.get("apiKeys", []))
    return list(result)
