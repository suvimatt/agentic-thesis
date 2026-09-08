---
title: 运维
description: 运行、备份、升级 AgenticThesis 自托管实例并排查问题。
---

## 持久状态

`agentic-thesis serve` 将所有本地状态保存在所选 `--data-dir` 下：

- 应用 SQLite 数据，包括 Thesis、事件、工件、Radar 条目、运行和修订；
- 用于恢复中断工作的 LangGraph SQLite 检查点；
- 嵌入式 Qdrant 索引；
- 可选的本地配置 `.env` 文件。

向量索引是派生数据。来源工件、事件标识、证据定位器、运行历史和 Thesis snapshot 才是权威记录。

## 备份与恢复

1. 停止本地服务器，避免 SQLite 与 Qdrant 正在写入。
2. 将完整数据目录复制到受保护的存储位置。
3. 如果备份目标未获准保存密钥，请单独保管 `.env`。
4. 将完整目录恢复到相同的 AgenticThesis schema 版本。
5. 启动服务器，并核对 Thesis、Radar、待审核项和修订列表。

不要只备份 Qdrant。脱离应用状态的向量无法重建权威 Thesis 历史。

## 为 v1.1 全新启动

v1.1 使用全新 schema；遇到早期或预发布版本的数据目录时会拒绝启动且不会修改它。使用默认空目录启动：

```bash
agentic-thesis serve
```

项目不提供迁移到 v1.1 的工具。如果默认目录已有旧数据，请选择另一个空的 `--data-dir`。

## SEC 访问

启用 SEC 收集前，设置真实的身份标识：

```dotenv
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

默认情况下，调度器每小时检查一次是否需要收集；每 24 小时最多记录一次成功收集。`AGENTIC_THESIS_SEC_POLL_SECONDS` 修改进程内的到期检查间隔，并不构成分布式调度保证。

## 安全与私有数据

- 切勿提交 `.env`、API key、投资者笔记或用户数据目录。
- 除非在项目外部增加认证与传输安全，否则仅将打包服务器绑定到 localhost。
- 将发行人页面、filing、上传的 HTML/PDF 和模型输出都视为不可信输入。
- 保持 Human Review 启用；模型输出本身永远不具备权威性。
- 工件下载使用附件 disposition、`application/octet-stream` 和 `nosniff`，避免浏览器渲染已保存的来源内容。

## 故障排查

| 现象 | 检查项 |
| --- | --- |
| CLI 列出缺失变量 | 在生效的 `.env` 中填入所需推理与嵌入凭据 |
| SEC 同步返回 `503` | 设置 `AGENTIC_THESIS_SEC_USER_AGENT` 并重启应用 |
| SEC/IR 同步返回 `502` | 检查 `/collection-attempts` 和每个事件的失败；检查失败不等于“没有变化” |
| 数据库被拒绝 | 使用全新空数据目录启动 v1.1 |
| PDF 显示 `needs_ocr` | 通过引擎提供明确且有边界的 OCR 函数；项目不会下载 OCR 模型 |
| 批准返回 `409` | 重新加载最新 Thesis；另一项审核已推进其权威版本 |
