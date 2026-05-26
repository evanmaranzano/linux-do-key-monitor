# linux.do Key Monitor

实时监控 linux.do 福利区公开分享的促销 API key（小米 MiMo），自动发现、验证并写入 CC Switch。

## 功能

- 每 5 分钟轮询 linux.do 福利区
- 两阶段筛选：关键词标题过滤 + regex 内容提取
- 自动验证 key 有效性，支持多区域（CN / SGP）
- 发现有效 key 自动写入 CC Switch（未启用），按区域设置对应 base URL
- 发现有效 CN key 自动同步到 CCX Desktop config.json，失效 key 自动移除
- base64 编码 key 自动解码
- 终端实时输出 + JSON 文件记录

## 安装

```bash
pip install scrapling pyyaml
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

filter:
  keywords:              # 标题关键词
    - "mimo"
    - "小米"
  exclude_keywords:      # 排除关键词
    - "已用完"
    - "已结束"

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
```

## CC Switch 集成

发现有效 key 自动写入 CC Switch 数据库，`is_current=0`（未启用），在 CC Switch 应用中手动切换即可。

## CCX Desktop 集成

发现有效 CN key 自动同步到 CCX Desktop 的 `config.json`（`upstream[0].apiKeys`）。定期重新验证已同步的 key，失效的自动移除。

```yaml
ccx_sync:
  enabled: true
  config_path: "C:/Users/Administrator/AppData/Roaming/ccx-desktop/.config/config.json"
  reverify_interval: 3   # 每 N 轮全量重验 CCX 中的 key
```

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
├── switcher.py        # CC Switch 写入
└── ccx_sync.py        # CCX Desktop config.json 同步
```

## License

MIT
