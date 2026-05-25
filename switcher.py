import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from scrapling.fetchers import Fetcher

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


def create_switch(db_path: str, key_value: str, key_type: str = "mimo", base_url: str = "https://token-plan-cn.xiaomimimo.com/anthropic") -> bool:
    db = Path(db_path)
    if not db.exists():
        print(f"[!] CC Switch 数据库不存在: {db}")
        return False

    settings = json.loads(json.dumps(PROVIDER_TEMPLATE))
    settings["env"]["ANTHROPIC_AUTH_TOKEN"] = key_value
    settings["env"]["ANTHROPIC_BASE_URL"] = base_url

    with sqlite3.connect(str(db)) as conn:
        # 去重：已有同 key 的 provider 则跳过
        existing = conn.execute(
            "SELECT 1 FROM providers WHERE settings_config LIKE ? LIMIT 1",
            (f'%{key_value}%',)
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
    print(f"[{ts}] CC Switch 新建 provider: {name}")
    return True


def _extract_key_from_settings(settings_config: str) -> tuple[str, str] | None:
    """从 provider settings_config 提取 key 和 base_url。"""
    try:
        cfg = json.loads(settings_config)
        env = cfg.get("env", {})
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        base_url = env.get("ANTHROPIC_BASE_URL", "")
        if token:
            return token, base_url
    except Exception:
        pass
    return None


def _verify_provider_key(key_value: str, base_url: str) -> bool:
    """通过发送最小 chat 请求验证 key 是否有可用额度。"""
    # base_url 形如 https://token-plan-cn.xiaomimimo.com/anthropic
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
    try:
        resp = Fetcher.post(chat_url, headers=headers, data=body, timeout=15)
        # 200 = 有额度可用; 401/403 = key 无效; 429 = 额度用尽/限流
        if resp.status == 200:
            return True
        # 429 或包含 quota/rate/balance 相关信息视为额度用尽
        if resp.status == 429:
            return False
        body_text = ""
        try:
            body_text = resp.text.lower()
        except Exception:
            pass
        if any(kw in body_text for kw in ("quota", "rate", "balance", "insufficient", "exceeded", "limit")):
            return False
        # 401/403 = key 无效
        if resp.status in (401, 403):
            return False
        # 其他错误（500 等）暂不判定为失效
        return True
    except Exception:
        return False


def cleanup_expired_providers(db_path: str) -> tuple[int, int]:
    """检查所有 monitor 创建的 provider，移除已失效的。返回 (检查数, 移除数)。"""
    db = Path(db_path)
    if not db.exists():
        return 0, 0

    checked = 0
    removed = 0
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT id, name, settings_config, is_current FROM providers WHERE name LIKE 'MiMo Auto%'"
        ).fetchall()

        for row in rows:
            provider_id, name, settings_config, is_current = row
            extracted = _extract_key_from_settings(settings_config)
            if not extracted:
                continue

            key_value, base_url = extracted
            checked += 1

            if not _verify_provider_key(key_value, base_url):
                # 跳过当前激活的，避免断连
                if is_current:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] CC Switch 清理: 跳过激活中的失效 provider: {name}")
                    continue
                conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
                removed += 1

        conn.commit()

    ts = datetime.now().strftime("%H:%M:%S")
    if removed:
        print(f"[{ts}] CC Switch 清理: 检查 {checked} 个, 移除 {removed} 个失效 provider")
    else:
        print(f"[{ts}] CC Switch 清理: 检查 {checked} 个, 全部有效")
    return checked, removed
