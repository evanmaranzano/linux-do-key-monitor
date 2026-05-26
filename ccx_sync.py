import json
import os
import tempfile
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
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, str(path))
        return True
    except Exception as e:
        _log(f"写入配置失败: {e}")
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def add_key_to_ccx(config_path: str, key_value: str) -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    upstreams = cfg.get("upstream", [])
    if not upstreams:
        _log("无 upstream 配置")
        return False

    api_keys = upstreams[0].get("apiKeys", [])
    if key_value in api_keys:
        return True

    api_keys.append(key_value)
    upstreams[0]["apiKeys"] = api_keys

    if _write_config(config_path, cfg):
        _log(f"添加 key {key_value[:12]}... (共 {len(api_keys)} 个)")
        return True
    return False


def remove_key_from_ccx(config_path: str, key_value: str) -> bool:
    cfg = _read_config(config_path)
    if cfg is None:
        return False

    upstreams = cfg.get("upstream", [])
    if not upstreams:
        return False

    api_keys = upstreams[0].get("apiKeys", [])
    if key_value not in api_keys:
        return True

    api_keys.remove(key_value)
    upstreams[0]["apiKeys"] = api_keys

    if _write_config(config_path, cfg):
        _log(f"移除失效 key {key_value[:12]}... (剩余 {len(api_keys)} 个)")
        return True
    return False


def get_ccx_keys(config_path: str) -> list[str]:
    cfg = _read_config(config_path)
    if cfg is None:
        return []
    upstreams = cfg.get("upstream", [])
    if not upstreams:
        return []
    return upstreams[0].get("apiKeys", [])
