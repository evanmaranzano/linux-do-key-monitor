# linux-do-key-monitor

## 项目概述

linux.do 论坛 key 监控器，自动抓取福利板块帖子、提取 API key、验证有效性并写入 CC Switch。

## 关键技术约束

- scrapling `Fetcher.post()` 的请求体参数是 `data=`，不是 `body=`。用 `body=` 会抛 TypeError。
- key 验证必须用 `/v1/messages` 发送实际 chat 请求，`/v1/models` 只验 auth 不验额度（key 能返回模型列表但实际 429 额度用尽）。
- CC Switch provider 去重逻辑在 `switcher.py:create_switch`，通过 `settings_config LIKE '%key%'` 查重。
- 清理逻辑只删 `name LIKE 'MiMo Auto%'` 的 provider，不动其他 provider。
- Python `dict.get(key, expensive_default)` 的 default 表达式会立即求值，即使 key 存在。若 default 访问不存在的键会 KeyError。应用 `if key in dict` 替代。

## 常用命令

```bash
pip install scrapling beautifulsoup4 requests   # 依赖
python monitor.py                    # 启动监控
python -m pytest tests/ -q           # 运行测试
```

## 环境配置
- scrapling 代理需在 `~/.bashrc` 中设置 `export http_proxy=http://127.0.0.1:7897`（curl_cffi 不读系统代理）
- CC Switch 数据库: `%APPDATA%/CC Switch/ccswitch.db`
- CCX 配置路径: `C:/Users/Administrator/Downloads/Compressed/ccx-windows/.config/config.json`
- CCX 可执行文件: `C:/Users/Administrator/Downloads/Compressed/ccx-windows/ccx-go.exe`

## 架构

- `monitor.py` — 主循环，每轮扫描 3 页，每轮清理失效 provider 和重新验证 CCX key
- `fetcher.py` — Discourse API 抓取
- `extractor.py` — key 提取（regex + 插入文字 + base64）和验证
- `switcher.py` — CC Switch provider 管理（创建 + 清理）
- `store.py` — SQLite 存储（seen_topics + found_keys）
- `output.py` — 日志和 JSON 输出
- `ccx_sync.py` — CCX config.json 读写（add/remove/get key），CCX config 变更时自动重启 ccx-go.exe
