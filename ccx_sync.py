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


def _add_key_to_section(cfg: dict, section: str, key_value: str) -> bool:
    upstreams = cfg.get(section, [])
    if not upstreams:
        return False
    api_keys = upstreams[0].get("apiKeys", [])
    if key_value in api_keys:
        return False
    api_keys.append(key_value)
    upstreams[0]["apiKeys"] = api_keys
    return True


def add_key_to_ccx(config_path: str, key_value: str) -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    changed = False
    if _add_key_to_section(cfg, "upstream", key_value):
        changed = True
    if _add_key_to_section(cfg, "responsesUpstream", key_value):
        changed = True

    if changed and _write_config(config_path, cfg):
        count_u = len(cfg.get("upstream", [{}])[0].get("apiKeys", []))
        count_r = len(cfg.get("responsesUpstream", [{}])[0].get("apiKeys", []))
        _log(f"添加 key {key_value[:6]}...{key_value[-4:]} (upstream={count_u}, responses={count_r})")
        return True
    return False


def _remove_key_from_section(cfg: dict, section: str, key_value: str) -> bool:
    upstreams = cfg.get(section, [])
    if not upstreams:
        return False
    api_keys = upstreams[0].get("apiKeys", [])
    if key_value not in api_keys:
        return False
    api_keys.remove(key_value)
    upstreams[0]["apiKeys"] = api_keys
    return True


def remove_key_from_ccx(config_path: str, key_value: str) -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    changed = False
    if _remove_key_from_section(cfg, "upstream", key_value):
        changed = True
    if _remove_key_from_section(cfg, "responsesUpstream", key_value):
        changed = True

    if changed and _write_config(config_path, cfg):
        count_u = len(cfg.get("upstream", [{}])[0].get("apiKeys", []))
        count_r = len(cfg.get("responsesUpstream", [{}])[0].get("apiKeys", []))
        _log(f"移除失效 key {key_value[:6]}...{key_value[-4:]} (upstream={count_u}, responses={count_r})")
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
