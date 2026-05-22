import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

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


def create_switch(db_path: str, key_value: str) -> bool:
    db = Path(db_path)
    if not db.exists():
        print(f"[!] CC Switch 数据库不存在: {db}")
        return False

    settings = json.loads(json.dumps(PROVIDER_TEMPLATE))
    settings["env"]["ANTHROPIC_AUTH_TOKEN"] = key_value

    conn = sqlite3.connect(str(db))
    provider_id = str(uuid.uuid4())
    now_ts = int(datetime.now().timestamp())
    date_str = datetime.now().strftime("%m-%d %H:%M")
    name = f"MiMo Auto {date_str}"

    conn.execute(
        """INSERT INTO providers (id, app_type, name, settings_config, category, meta, is_current, created_at)
           VALUES (?, 'claude', ?, ?, 'cn_official', ?, 0, ?)""",
        (provider_id, name, json.dumps(settings, ensure_ascii=False), '{"commonConfigEnabled":false,"endpointAutoSelect":true,"apiFormat":"anthropic"}', now_ts),
    )
    conn.commit()
    conn.close()

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CC Switch 新建 provider: {name}（未启用）")
    return True
