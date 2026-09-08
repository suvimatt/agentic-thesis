---
title: 架构
description: 了解 AgenticThesis 如何分离来源保管、检索、模型工作、审核与持久状态。
---

[![AgenticThesis 架构](/agentic-thesis-architecture.svg)](/agentic-thesis-architecture.html)

可编辑的架构图以[独立 HTML 源文件](/agentic-thesis-architecture.html)提供。

在 v1.1 中，只有带可用披露的 `needs_review` 事件才会注册分析运行；`digest` 和 `ignored` 事件保留在 Radar 中，不启动分析。每次运行只绑定一份披露。

## 职责边界

| 层 | 职责 |
| --- | --- |
| 收集 | 发现已配置的 SEC/IR 事件，并在解释前保存精确工件 |
| 解析 | 生成稳定且可定位来源的句子、列表项、表格行和 PDF 页跨度 |
| Radar | 确定性判断事件需要审核、进入摘要还是忽略 |
| 检索 | 组合词法与向量候选，按条件重排，并打包有边界的证据 |
| 分析 | 仅根据提供的证据，逐 Claim 生成类型化 `ThesisDelta` |
| 完整性 | 校验 Evidence ID、精确引文、偏移、Claim 与 Falsifier |
| 审核 | 暂停并等待投资者批准、编辑或拒绝拟议变更 |
| 提交 | 仅当基础 Thesis 版本仍为当前版本时应用获批 delta |

## 存储职责

- **应用 SQLite** 是事件、工件、Radar、运行、Thesis head、snapshot 和 revision 的权威记录。
- **检查点 SQLite** 单独保存可恢复的 LangGraph 执行状态，不与应用事务混合。
- **嵌入式 Qdrant** 保存本地检索向量，可从规范 chunk 重建。
- **原始工件字节与哈希** 让每段获准引用都能追溯到抓取的来源版本。

IR 变化检测会对规范化可见内容生成指纹，避免动态脚本制造重复披露；保存的工件哈希仍标识原始字节。向量索引、检索查询和分析都有明确超时。检查点恢复使用明确的工作流类型反序列化 allowlist。

## 为什么只有一个工作流

AgenticThesis 只有一个由应用自身拥有、包含六个明确状态转换的 LangGraph。它不是一组自治 Agent。检索、校验、提交和冲突保护仍由确定性代码负责；模型仅用于嵌入、条件式重排和结构化比较。

这让 Context、Memory 与 Workflow State 保持分离：

- **Context** 是为单个 Claim 临时提供、经查询筛选的证据。
- **Memory** 是获批、不可变的 Thesis snapshot 与修订历史。
- **Workflow State** 是活动中或已审核运行的可恢复执行记录。

## 来源边界

SEC 与发行人拥有的工件可以成为权威证据。二手来源可以提出线索，但不能独立授权修订。模型无法仅凭把低权威来源描述为“官方”就提升其等级。
