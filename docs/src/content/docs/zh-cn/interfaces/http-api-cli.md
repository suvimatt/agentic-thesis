---
title: HTTP API 与 CLI
description: 运行自托管应用，并使用关键 HTTP 工作流。
---

## CLI

```bash
agentic-thesis serve [--data-dir PATH]
```

服务器监听 `127.0.0.1:8000`。配置先从当前目录的 `.env` 加载，再从所选数据目录的 `.env` 加载。默认数据目录为 `~/.agentic-thesis`。

在 `/` 打开应用。公开的 [API Reference](/zh-cn/api/) 根据与应用相同的 FastAPI OpenAPI schema 生成；接口名称和 schema 仍以英文为权威来源。[`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs) 仍可作为实例本地的 API 调试器。

## 关键工作流

为一个已有 Thesis 和一份披露创建运行：

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"run_id":"aapl-review","thesis_id":"aapl","disclosure_id":"aapl-2026-q2"}'
```

跟踪持久事件。使用 `Last-Event-ID` 重连，只重放后续事件：

```bash
curl -N http://127.0.0.1:8000/runs/aapl-review/events
```

检查拟议 delta 和引用的来源文本后批准：

```bash
curl -X POST http://127.0.0.1:8000/runs/aapl-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

## 监控

配置并检查 SEC：

```bash
curl -X PUT http://127.0.0.1:8000/theses/aapl/monitor \
  -H 'content-type: application/json' \
  -d '{"cik":"320193","forms":["10-K","10-Q","8-K"],"enabled":true}'

curl -X POST http://127.0.0.1:8000/theses/aapl/sync
```

配置并检查可信的发行人 IR 页面：

```bash
curl -X PUT http://127.0.0.1:8000/theses/aapl/ir-monitor \
  -H 'content-type: application/json' \
  -d '{"urls":["https://www.example.com/investors"],"enabled":true}'

curl -X POST http://127.0.0.1:8000/theses/aapl/ir-sync
```

使用 `/events/{event_id}`、`/events/{event_id}/artifacts`、`/events/{event_id}/failures`、`/collection-attempts` 和 `/radar` 检查发现、保存、遗漏和路由结果。通过 `/artifacts/{artifact_id}` 获取原始字节。

## 错误语义

| 状态码 | 含义 |
| --- | --- |
| `400` | 协议输入无效，例如非整数 `Last-Event-ID` |
| `404` | 请求的 Thesis、披露、运行、事件或监控不存在 |
| `409` | 标识重复、监控暂停或 Thesis 版本过期 |
| `422` | 领域输入或编辑后的审核无效 |
| `502` | 上游 SEC/IR 收集失败；失败的尝试仍会被记录 |
| `503` | SEC 监控缺少必要的标识 User-Agent |
