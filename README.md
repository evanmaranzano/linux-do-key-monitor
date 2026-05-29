# linux.do Key Monitor

实时监控 linux.do 福利区公开分享的促销 API key（小米 MiMo），自动发现、验证并写入 CC Switch / CCX Desktop。

## 功能

- 每 5 分钟轮询 linux.do 福利区
- 两阶段筛选：关键词标题过滤 + regex 内容提取
- 自动验证 key 有效性，支持多区域（CN / SGP）
- 发现有效 key 自动写入 CC Switch（未启用），按区域设置对应 base URL
- CC Switch 支持 Claude + Codex 双 provider，自动创建和验证
- 发现有效 CN key 自动同步到 CCX Desktop config.json，失效 key 自动移除
- SSRF 防护：拒绝内网/回环地址，DNS 解析验证
- base64 编码 key 自动解码
- 终端实时输出 + JSON 文件记录

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
# 启动监控
python monitor.py

# 自定义配置
python monitor.py --config custom.yaml
```

## 配置

编辑 `config.yaml`：

```yaml
monitor:
  interval: 300          # 轮询间隔（秒）
  max_pages: 3           # 每次拉取页数

filter:
  keywords:              # 标题关键词
    - "mimo"
    - "小米"
    - "token-plan"
  exclude_keywords:      # 排除关键词
    - "已用完"
    - "已结束"
    - "已蹬完"
    - "已登完"
    - "已无"

keys:
  - name: "mimo"
    pattern: "tp-[a-z0-9]{30,}"
    verify_type: "bearer"
    regions:             # 多区域验证
      - name: "cn"
        verify_url: "https://token-plan-cn.xiaomimimo.com/v1/models"
        base_url: "https://token-plan-cn.xiaomimimo.com/anthropic"
      - name: "sgp"
        verify_url: "https://token-plan-sgp.xiaomimimo.com/v1/models"
        base_url: "https://token-plan-sgp.xiaomimimo.com/anthropic"

cc_switch:
  enabled: true
  db_path: "C:/Users/Administrator/.cc-switch/cc-switch.db"
  key_type: "mimo"

ccx_sync:
  enabled: true
  config_path: "C:/Users/Administrator/Downloads/Compressed/ccx-windows/.config/config.json"
  reverify_interval: 3   # 每 N 轮全量重验 CCX 中的 key
  exe_path: "C:/Users/Administrator/Downloads/Compressed/ccx-windows/ccx-go.exe"

output:
  json_path: "data/found_keys.json"
  db_path: "data/keys.db"
```

## CC Switch 集成

发现有效 key 自动写入 CC Switch 数据库，同时创建 **Claude** 和 **Codex** 两个 provider：

- **Claude provider**：使用原始 base URL，key 类型为 `mimo`
- **Codex provider**：自动将 base URL 从 `/anthropic` 转换为 `/codex` 路径

创建前自动验证 key 有效性，`is_current=0`（未启用），在 CC Switch 应用中手动切换即可。定期自动清理过期 provider。

## CCX Desktop 集成

发现有效 CN key 自动同步到 CCX Desktop 的 `config.json`（`upstream[0].apiKeys`）。定期重新验证已同步的 key，失效的自动移除。

## 安全

`security.py` 提供 URL 安全校验：

- 拒绝非 http/https 协议
- 拒绝 localhost、回环地址、内网地址
- DNS 解析后二次验证，防止 DNS rebinding
- DNS 解析失败时放行（不误判为内网阻塞启动）

## 注意事项

- scrapling `Fetcher.post()` 请求体参数是 `data=`，不是 `body=`（TypeError 会被静默吞掉）
- key 验证必须用 `/v1/messages` 发实际 chat 请求，`/v1/models` 只验 auth 不验额度
- scrapling 代理需在 `~/.bashrc` 设置 `export http_proxy=http://127.0.0.1:7897`（curl_cffi 不读系统代理）

## 项目结构

```
├── config.yaml        # 配置文件
├── monitor.py         # 主入口
├── fetcher.py         # Discourse API 请求
├── extractor.py       # 关键词过滤 + regex 提取
├── store.py           # SQLite 存储
├── output.py          # 输出格式化
├── switcher.py        # CC Switch 写入（Claude + Codex 双 provider）
├── ccx_sync.py        # CCX Desktop config.json 同步
├── security.py        # SSRF 防护、URL 安全校验
├── requirements.txt   # Python 依赖
├── tests/             # 测试
├── docs/              # 文档
└── data/              # 运行时数据（found_keys.json、keys.db）
```

## License

MIT