# linux-do-key-monitor

## 项目概述

linux.do 论坛 key 监控器，自动抓取福利板块帖子、提取 API key、验证有效性并写入 CC Switch。

## 关键技术约束

- scrapling `Fetcher.post()` 的请求体参数是 `data=`，不是 `body=`。用 `body=` 会抛 TypeError。
- key 验证必须用 `/v1/messages` 发送实际 chat 请求，`/v1/models` 只验 auth 不验额度（key 能返回模型列表但实际 429 额度用尽）。
- CC Switch provider 去重逻辑在 `switcher.py:create_switch`，通过 `settings_config LIKE '%key%'` 查重。
- 清理逻辑只删 `name LIKE 'MiMo Auto%'` 的 provider，不动其他 provider。

## 常用命令

```bash
python monitor.py                    # 启动监控
python -m pytest tests/ -q           # 运行测试
```

## 架构

- `monitor.py` — 主循环，每轮扫描 3 页，每 5 轮清理失效 provider
- `fetcher.py` — Discourse API 抓取
- `extractor.py` — key 提取（regex + 插入文字 + base64）和验证
- `switcher.py` — CC Switch provider 管理（创建 + 清理）
- `store.py` — SQLite 存储（seen_topics + found_keys）
- `output.py` — 日志和 JSON 输出
