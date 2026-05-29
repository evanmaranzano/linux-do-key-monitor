import json
import logging
import sqlite3
import re
import uuid
from datetime import datetime
from pathlib import Path

_logger = logging.getLogger(__name__)

from scrapling.fetchers import Fetcher
from security import is_safe_url


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

PROVIDER_TEMPLATE = {
    "attribution": {"commit": "", "pr": ""},
    "effortLevel": "xhigh",
    "enabledPlugins": {
        "claude-code-setup@claude-plugins-official": True,
        "claude-md-management@claude-plugins-official": True,
        "code-review@claude-plugins-official": True,
        "code-simplifier@claude-plugins-official": True,
        "commit-commands@claude-plugins-official": True,
        "context7@claude-plugins-official": True,
        "figma@claude-plugins-official": True,
        "frontend-design@claude-plugins-official": True,
        "github@claude-plugins-official": True,
        "playwright@claude-plugins-official": True,
        "ralph-loop@claude-plugins-official": True,
        "security-guidance@claude-plugins-official": True,
        "skill-creator@claude-plugins-official": True,
        "superpowers@claude-plugins-official": True,
    },
    "env": {
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "https://token-plan-cn.xiaomimimo.com/anthropic",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "mimo-v2.5-pro",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": "mimo-v2.5-pro",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "mimo-v2.5-pro[1M]",
        "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": "mimo-v2.5-pro",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "mimo-v2.5-pro[1M]",
        "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "mimo-v2.5-pro",
        "ANTHROPIC_MODEL": "mimo-v2.5-pro",
        "CLAUDE_CODE_EFFORT_LEVEL": "max",
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
        "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1",
        "ENABLE_TOOL_SEARCH": "true",
    },
    "hooks": {
        "PostToolUse": [
            {"hooks": [{"command": "bash -c 'echo \"$CLAUDE_FILE_PATH\" | grep -qE \"\\\\.(js|ts|jsx|tsx|json|css)$\" && npx prettier --write \"$CLAUDE_FILE_PATH\" 2>/dev/null || true'", "type": "command"}], "matcher": "Write"},
            {"hooks": [{"command": "bash ~/.claude/hooks/bash-logger.sh", "type": "command"}], "matcher": "Bash"},
        ],
        "PreToolUse": [
            {"hooks": [{"command": "bash -c 'echo \"$CLAUDE_FILE_PATH\" | grep -qE \"(\\\\.env$|\\\\.claude\\\\.json$|secrets|credentials)\" && echo \"BLOCKED: refusing to edit sensitive file\" && exit 1 || exit 0'", "type": "command"}], "matcher": "Edit|Write"},
            {"hooks": [{"command": "bash ~/.claude/hooks/git-safety-guardian.sh", "type": "command"}], "matcher": "Bash"},
            {"hooks": [{"command": "bash ~/.claude/hooks/recursion-guard.sh", "type": "command"}], "matcher": "Agent|Task"},
        ],
        "Stop": [{"hooks": [{"command": "bash ~/.claude/hooks/stop-quality-gate.sh", "type": "command"}]}],
        "UserPromptSubmit": [{"hooks": [{"command": "bash ~/.claude/hooks/context-injector.sh", "type": "command"}]}],
    },
    "includeCoAuthoredBy": False,
    "model": "opus",
    "skipDangerousModePermissionPrompt": True,
    "statusLine": {
        "command": "cols=$(stty size </dev/tty 2>/dev/null | awk '{print $2}'); export COLUMNS=$(( ${cols:-120} > 4 ? ${cols:-120} - 4 : 1 )); plugin_dir=$(ls -1d \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}\"/plugins/cache/*/claude-hud/*/ 2>/dev/null | sort -V | tail -1); exec \"/c/Program Files/nodejs/node\" \"${plugin_dir}dist/index.js\"",
        "type": "command",
    },
    "theme": "dark",
    "tui": "fullscreen",
}


CODEX_PROVIDER_TEMPLATE = """\
model_provider = "MiMo-Monitor"
model = "mimo-v2.5-pro"
model_reasoning_effort = "xhigh"

[model_providers.MiMo-Monitor]
name = "MiMo-Monitor"
wire_api = "responses"
requires_openai_auth = true
base_url = "{base_url}"
experimental_bearer_token = "{key_value}"
"""


def create_switch(db_path: str, key_value: str, key_type: str = "mimo", base_url: str = "https://token-plan-cn.xiaomimimo.com/anthropic") -> bool:
    db = Path(db_path)
    if not db.exists():
        print(f"[!] CC Switch 数据库不存在: {db}")
        return False

    if not is_safe_url(base_url):
        print(f"[!] CC Switch: 拒绝不安全的 base_url: {base_url}")
        return False

    ok_claude = _create_claude_provider(db, key_value, key_type, base_url)
    ok_codex = _create_codex_provider(db, key_value, base_url)
    return ok_claude or ok_codex


def _create_claude_provider(db: Path, key_value: str, key_type: str, base_url: str) -> bool:
    settings = json.loads(json.dumps(PROVIDER_TEMPLATE))
    settings["env"]["ANTHROPIC_AUTH_TOKEN"] = key_value
    settings["env"]["ANTHROPIC_BASE_URL"] = base_url

    with sqlite3.connect(str(db)) as conn:
        escaped = _escape_like(key_value)
        existing = conn.execute(
            "SELECT 1 FROM providers WHERE app_type='claude' AND settings_config LIKE ? ESCAPE '\\' LIMIT 1",
            (f'%{escaped}%',)
        ).fetchone()
        if existing:
            return True

        provider_id = str(uuid.uuid4())
        now_ts = int(datetime.now().timestamp())
        date_str = datetime.now().strftime("%m-%d %H:%M")
        region_tag = ""
        if "sgp" in base_url:
            region_tag = " SGP"
        elif "cn" in base_url:
            region_tag = " CN"
        name = f"MiMo Auto{region_tag} {date_str}"

        conn.execute(
            """INSERT INTO providers (id, app_type, name, settings_config, category, meta, is_current, created_at)
               VALUES (?, 'claude', ?, ?, 'cn_official', ?, 0, ?)""",
            (provider_id, name, json.dumps(settings, ensure_ascii=False), '{"commonConfigEnabled":false,"endpointAutoSelect":true,"apiFormat":"anthropic"}', now_ts),
        )
        conn.commit()

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CC Switch (Claude) 新建 provider: {name}")
    return True


def _codex_base_url(anthropic_base_url: str) -> str:
    """将 Anthropic 格式 base_url 转为 Codex 需要的 OpenAI 格式。"""
    url = anthropic_base_url.rstrip("/")
    # https://token-plan-cn.xiaomimimo.com/anthropic -> https://token-plan-cn.xiaomimimo.com/v1
    url = re.sub(r'/anthropic$', '/v1', url)
    # https://token-plan-sgp.xiaomimimo.com/anthropic -> https://token-plan-sgp.xiaomimimo.com/v1
    if not url.endswith("/v1"):
        url = url + "/v1"
    return url


def _create_codex_provider(db: Path, key_value: str, anthropic_base_url: str) -> bool:
    base_url = _codex_base_url(anthropic_base_url)
    config_str = CODEX_PROVIDER_TEMPLATE.format(base_url=base_url, key_value=key_value)
    settings = {
        "auth": {"OPENAI_API_KEY": key_value},
        "config": config_str,
    }
    settings_json = json.dumps(settings, ensure_ascii=False)

    with sqlite3.connect(str(db)) as conn:
        escaped = _escape_like(key_value)
        existing = conn.execute(
            "SELECT 1 FROM providers WHERE app_type='codex' AND settings_config LIKE ? ESCAPE '\\' LIMIT 1",
            (f'%{escaped}%',)
        ).fetchone()
        if existing:
            return True

        provider_id = str(uuid.uuid4())
        now_ts = int(datetime.now().timestamp())
        date_str = datetime.now().strftime("%m-%d %H:%M")
        region_tag = ""
        if "sgp" in anthropic_base_url:
            region_tag = " SGP"
        elif "cn" in anthropic_base_url:
            region_tag = " CN"
        name = f"MiMo Auto{region_tag} {date_str}"

        conn.execute(
            """INSERT INTO providers (id, app_type, name, settings_config, category, meta, is_current, created_at)
               VALUES (?, 'codex', ?, ?, NULL, ?, 0, ?)""",
            (provider_id, name, settings_json, '{"commonConfigEnabled":false,"endpointAutoSelect":true}', now_ts),
        )
        conn.commit()

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CC Switch (Codex) 新建 provider: {name}")
    return True


def _extract_key_from_settings(settings_config: str) -> tuple[str, str] | None:
    """从 provider settings_config 提取 key 和 base_url。支持 claude 和 codex 两种格式。"""
    try:
        cfg = json.loads(settings_config)
    except Exception:
        return None
    # Claude 格式: env.ANTHROPIC_AUTH_TOKEN
    env = cfg.get("env", {})
    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    base_url = env.get("ANTHROPIC_BASE_URL", "")
    if token:
        return token, base_url
    # Codex 格式: auth.OPENAI_API_KEY
    auth = cfg.get("auth", {})
    token = auth.get("OPENAI_API_KEY", "")
    if token:
        # 从 TOML config 提取 base_url
        config_str = cfg.get("config", "")
        m = re.search(r'base_url\s*=\s*"([^"]+)"', config_str)
        codex_base = m.group(1) if m else ""
        return token, codex_base
    return None


def _verify_provider_key(key_value: str, base_url: str, app_type: str = "claude") -> bool:
    """验证 key 是否有可用额度。根据 app_type 选择对应 API 格式。"""
    if app_type == "codex":
        return _verify_codex_key(key_value, base_url)
    return _verify_claude_key(key_value, base_url)


def _verify_claude_key(key_value: str, base_url: str) -> bool:
    """通过 Anthropic /v1/messages 验证 key。"""
    if not is_safe_url(base_url):
        _logger.warning("拒绝验证不安全的 base_url: %s", base_url)
        return False
    chat_url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": key_value,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = json.dumps({
        "model": "mimo-v2.5-pro",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    })
    return _do_verify_request(chat_url, headers, body)


def _verify_codex_key(key_value: str, base_url: str) -> bool:
    """通过 OpenAI 兼容 /v1/chat/completions 验证 key。"""
    if not is_safe_url(base_url):
        _logger.warning("拒绝验证不安全的 base_url: %s", base_url)
        return False
    chat_url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {key_value}",
        "content-type": "application/json",
    }
    body = json.dumps({
        "model": "mimo-v2.5-pro",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    })
    return _do_verify_request(chat_url, headers, body)


def _do_verify_request(url: str, headers: dict, body: str) -> bool:
    """发送验证请求并判断结果。"""
    try:
        resp = Fetcher.post(url, headers=headers, data=body, timeout=30)
        if resp.status == 200:
            return True
        if resp.status == 429:
            return False
        body_text = ""
        try:
            body_text = resp.text.lower()
        except Exception:
            pass
        if any(kw in body_text for kw in ("quota", "rate", "balance", "insufficient", "exceeded", "limit")):
            return False
        if resp.status in (401, 403):
            return False
        return True
    except Exception as e:
        _logger.debug("验证 key 网络异常: %s", e)
        return True


def cleanup_expired_providers(db_path: str) -> tuple[int, int]:
    """检查所有 monitor 创建的 provider（claude + codex），移除已失效的。返回 (检查数, 移除数)。"""
    db = Path(db_path)
    if not db.exists():
        return 0, 0

    # 阶段 1：快速读取，立即释放连接
    rows = []
    with sqlite3.connect(str(db), timeout=5) as conn:
        rows = conn.execute(
            "SELECT id, app_type, name, settings_config, is_current FROM providers WHERE name LIKE 'MiMo Auto%'"
        ).fetchall()

    # 阶段 2：逐个验证 key（网络 I/O，不持有数据库锁）
    to_remove = []
    checked = 0
    for row in rows:
        provider_id, app_type, name, settings_config, is_current = row
        extracted = _extract_key_from_settings(settings_config)
        if not extracted:
            continue
        key_value, base_url = extracted
        checked += 1
        if not _verify_provider_key(key_value, base_url, app_type):
            if is_current:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] CC Switch 清理: 跳过激活中的失效 provider: {name}")
                continue
            to_remove.append(provider_id)

    # 阶段 3：批量删除，短连接
    removed = 0
    if to_remove:
        with sqlite3.connect(str(db), timeout=5) as conn:
            for pid in to_remove:
                conn.execute("DELETE FROM providers WHERE id = ?", (pid,))
            conn.commit()
        removed = len(to_remove)

    ts = datetime.now().strftime("%H:%M:%S")
    if removed:
        print(f"[{ts}] CC Switch 清理: 检查 {checked} 个, 移除 {removed} 个失效 provider")
    else:
        print(f"[{ts}] CC Switch 清理: 检查 {checked} 个, 全部有效")
    return checked, removed
