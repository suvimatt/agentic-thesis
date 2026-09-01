<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-1C3C3C" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="GPL-3.0 license"></a>
  <a href="https://github.com/suvimatt/agentic-thesis/stargazers"><img src="https://img.shields.io/github/stars/suvimatt/agentic-thesis?style=social" alt="GitHub stars"></a>
</p>

<h2 align="center">🚀 基于证据、持续维护投资 Thesis 的有状态 RAG 系统</h2>

AgenticThesis 判断一家公司的新披露如何支持、削弱或可能推翻投资者已有的 Thesis。材料既可以手工导入，也可以按指定类型监控 SEC EDGAR Filing。系统生成带原文引用的逐条判断变化，在 Human Review 处暂停，支持重启后继续，并阻止旧任务覆盖更新版本的 Thesis。

投资判断始终归用户所有。AgenticThesis 不输出 Buy / Sell / Hold 建议。

如果这个项目能帮助你构建更可靠的 AI 研究系统，欢迎点一个 Star。你的支持可以让更多开发者发现它，也会推动项目继续完善。

<p align="center">
  <a href="https://github.com/suvimatt/agentic-thesis">
    <img src="https://img.shields.io/badge/%E2%AD%90-Give%20AgenticThesis%20a%20Star-yellow?style=for-the-badge&logo=github" alt="Give AgenticThesis a Star">
  </a>
</p>

## 目录

- [🚀 快速开始](#-快速开始)
- [为什么需要 AgenticThesis](#为什么需要-agenticthesis)
- [投资哲学 → 工程决策](#投资哲学)
- [运行流程](#运行流程)
- [系统架构](#系统架构)
- [已实现能力](#已实现能力)
- [验证结果](#验证结果)
- [API 使用](#api-使用)
- [90 秒验证](#90-秒验证)
- [明确边界](#明确边界)
- [开源协议](#开源协议)

## 🚀 快速开始

### 1. 配置模型端点

创建 `~/.agentic-thesis/.env`，也可以使用当前目录下的 `.env`：

```bash
mkdir -p ~/.agentic-thesis
$EDITOR ~/.agentic-thesis/.env
```

填写以下配置：

| 变量 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 重排序和结构化 Thesis 分析使用的 API Key |
| `OPENAI_BASE_URL` | 推理模型的 OpenAI 兼容端点 |
| `AGENTIC_THESIS_MODEL` | 推理模型名称 |
| `EMBEDDING_API_KEY` | Embedding 端点的 API Key |
| `EMBEDDING_BASE_URL` | OpenAI 兼容的 Embedding 端点 |
| `AGENTIC_THESIS_EMBEDDING_MODEL` | Embedding 模型名称 |
| `AGENTIC_THESIS_SEC_USER_AGENT` | 产品/姓名和联系邮箱；仅 SEC 自动监控需要 |

SEC 要求自动访问程序声明可识别的操作者。例如：

```dotenv
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

### 2. 启动应用

```bash
uvx --from git+https://github.com/suvimatt/agentic-thesis agentic-thesis serve
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。首次启动会 seed 安装包内的 Apple thesis 和 filings。Thesis、手工导入的 disclosure、历史 runs、events、checkpoints 和已批准版本都会保存在 `~/.agentic-thesis/`，服务重启后继续使用。

开发和确定性验证：

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

测试在适当位置使用确定性的检索和模型替代实现，因此不调用外部模型也能验证核心状态保证。

## 为什么需要 AgenticThesis

普通 Filing 助手回答：*这份文件说了什么？*

AgenticThesis 回答一个更困难、需要持久状态的问题：*这份新证据如何改变我原来对公司的判断？*

| 一次性 Filing 助手 | AgenticThesis |
| --- | --- |
| 总结单份文件 | 把新披露与版本化 Thesis 对照 |
| 输出自由文本 | 输出结构化、逐条 claim 的 `ThesisDelta` |
| 把聊天记录当作 Memory | 保存不可变的 `ThesisSnapshot` 版本 |
| 可能输出无依据结论 | 验证每条引用是否真实存在于原文 |
| 生成完成即结束 | 权威状态变更前必须经过 Human Review |
| 重启后从头开始 | 从 SQLite checkpoint 恢复 |

<a id="投资哲学"></a>

## 投资哲学 → 工程决策

AgenticThesis 把段永平“不懂不投”的原则落实为系统边界，而不是模仿某位投资者的人格或生成投资建议：

- 证据不足或相互矛盾时输出 `unknown`，不强行给出结论；
- 用户预先定义 falsifier，让反证成为一等检验条件；`possibly_invalidated` 必须匹配明确的 falsifier；
- 系统从不输出 Buy / Sell / Hold 建议；
- Thesis 和最终投资判断始终归用户所有；
- 新证据只能生成可审核的 `ThesisDelta` proposal；只有明确通过 Human Review 后，系统才能修改权威 `ThesisSnapshot`。

## 运行流程

```text
手工 disclosure 或定时检查 SEC submissions
→ 按 accession/content 去重并持久化 Filing
→ ThesisSnapshot v1
→ 在基准 Filing 和新 Filing 上执行混合检索
→ 为每条 claim 构建受 token budget 约束的 EvidencePack
→ 生成结构化 ThesisDelta
→ 验证引用和 falsifier
→ Human Review
→ compare-and-swap 提交
→ ThesisSnapshot v2 或 version_conflict
```

每条 claim 只会得到四种状态之一：`supported`、`weakened`、`possibly_invalidated` 或 `unknown`。

## 系统架构

[![AgenticThesis 系统架构](docs/agentic-thesis-architecture.svg)](docs/agentic-thesis-architecture.html)

系统只有一个由应用拥有的 Workflow，而不是一组自治 Agent。LangGraph 协调六个明确的状态迁移；确定性代码负责检索融合、Context 预算、引用完整性和版本提交，LLM 只负责语义重排序和结构化 Thesis 比较。

| 边界 | 职责 | 实现 |
| --- | --- | --- |
| 接口 | 管理 theses 和 disclosures、检查指定 SEC filing types、异步启动任务、重放进度并接受审核决定 | FastAPI、后台 `asyncio` tasks、durable SSE |
| 检索 | 在 Filing 语料中找到与 claim 相关的段落 | 确定性固定长度切块及 section 标签、BM25、进程内 Qdrant vector、RRF、API rerank |
| Working Context | 为每条 claim 提供最小、充分、可定位来源的证据 | query-conditioned extractive `EvidencePack`、每条 claim 固定 2,000-token 预算、evidence ID 和原文偏移 |
| 语义分析 | 只根据提供的证据比较每条 Thesis claim | API Structured Outputs → 类型化 `ThesisDelta` |
| 完整性门禁 | 阻止无依据结论和不安全状态变更 | quote/source 校验、falsifier 校验、exact-claim 校验、Human Review |
| 持久状态 | 恢复运行中或暂停的任务并保存权威 Thesis 历史 | LangGraph SQLite checkpoint、durable run events、不可变 `ThesisSnapshot`、thesis head |
| 提交 | 只有 base version 仍为当前版本时才能应用已批准的 delta | SQLite compare-and-swap → `vN+1` 或 `version_conflict` |

两份仓库内 SEC Filing 经确定性 HTML 提取后共有 97,675 个 `cl100k_base` token。模型调用不会接收完整 Filing，而只接收逐条 claim 构建、带引用的 `EvidencePack`。这使 **Context**（当前调用的临时工作证据）、**Memory**（版本化 Thesis）和 **Workflow State**（可恢复执行状态）彼此分离。

架构图的可编辑源文件是 [`docs/agentic-thesis-architecture.html`](docs/agentic-thesis-architecture.html)，README 展示其导出的 SVG。

## 已实现能力

- 确定性的 SEC HTML 提取、带 section metadata 的固定长度切块、字符偏移和稳定 chunk ID；
- BM25 + Qdrant local vector retrieval、Reciprocal Rank Fusion 和基于 OpenAI API 的 listwise reranking；
- 带硬性 token budget、来源覆盖和 retained evidence ID 的 extractive Context compression；
- 使用 OpenAI Structured Outputs 实现四态 `ThesisDelta` contract；
- quote-to-source 引用校验；无依据输出会降级为 `unknown`；
- 六节点 LangGraph、Human Review interrupt 和 SQLite checkpoint/resume；
- 不可变 Thesis snapshot 和 compare-and-swap 冲突保护；
- 可持久化的 run history，以及通过 `Last-Event-ID` 跨浏览器或服务重启重放的顺序化 SSE；
- 多个相互隔离的 theses，以及手工 HTML/TXT disclosure 导入；
- 每个 thesis 一个官方 SEC EDGAR monitor，可选择 filing types，按 accession/content 去重，支持手工 sync 和持久化的每日收集 schedule；
- 异步 FastAPI、后台任务、有界且带 timeout 的模型调用、停止服务后的 checkpoint 恢复，以及不暴露 chain-of-thought 的实时 LangGraph events；
- 无前端依赖的产品页面，支持 thesis/disclosure 管理、进度、引用、Context 压缩和 Human Review；
- 可安装的 `agentic-thesis serve` CLI、package sample data 和稳定的用户数据目录。

## 验证结果

2026-09-01 在仓库内 fixture 上的观测结果：

| 检查项 | 观测结果 |
| --- | ---: |
| 测试 | 15 passed |
| 全新环境 wheel 安装 | 在仓库外验证通过 |
| 2023 提取 tokens / chunks | 48,923 / 109 |
| 2024 提取 tokens / chunks | 48,752 / 110 |
| BM25 Recall@5 | 1.00 |
| 确定性 fake-vector Recall@5 | 0.60 |
| RRF hybrid Recall@5 | 1.00 |
| 确定性 fake-rerank Recall@5 | 1.00 |
| 压缩后保留 gold evidence | 5 / 5 |
| 伪造引用 | 降级为 `unknown` |
| 重启与恢复 | 使用相同 run ID 提交 v2 |
| 旧版本写入 | 返回 `version_conflict` / HTTP 409 |

Recall 使用 `evals/gold.json` 中的五个案例。确定性的 vector 和 rerank 数据用于验证编排与指标计算。

仓库内的 `evals/live_results.json` 记录了一次覆盖两份 Filing（219 chunks）的真实 API 运行，模型为 `qwen3.7-text-embedding` 和 `gpt-5.6-luna`：

| Live 检查项 | 观测结果 |
| --- | ---: |
| BM25 / vector / hybrid / rerank Recall@5 | 1.00 / 0.80 / 1.00 / 1.00 |
| Gold 排名，hybrid → rerank | 2→2, 1→1, 2→2, 4→5, 3→3 |
| 压缩后保留 gold evidence | 5 / 5 |
| 校验后的 claim 状态 | supported / possibly_invalidated / weakened |
| Embedding index | 8.73 s |
| 五条 query rerank evaluation | 38.17 s |
| 三条 claim structured analysis | 16.18 s |

在这五条 query 上，reranker 保持了 Recall@5，但没有改善 gold position，其中一个案例从第 4 位降到第 5 位。这些时间来自一次实测运行，不代表 latency benchmark 或 production SLO。

重新运行 live evaluation：

```bash
.venv/bin/python evals/run_live.py
```

报告会写入 `evals/live_results.json`，其中不会包含 API Key。

## API 使用

启动任务、流式读取事件，然后提交审核决定：

```bash
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"run_id":"aapl-2024-review","thesis_id":"aapl-primary"}'

curl -N http://localhost:8000/runs/aapl-2024-review/events

curl -X POST http://localhost:8000/runs/aapl-2024-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

配置并立即检查 SEC monitor：

```bash
curl -X PUT http://localhost:8000/theses/aapl-primary/monitor \
  -H 'content-type: application/json' \
  -d '{"cik":"320193","forms":["10-K","10-Q","8-K"],"enabled":true}'

curl -X POST http://localhost:8000/theses/aapl-primary/sync
```

第一次成功检查只导入最新一份符合条件的 Filing，用它建立 cursor，不自动回填全部历史。服务启动时判断是否到期，运行期间每小时只检查一次本地 due state；自动收集只在距离上次成功收集满 24 小时后访问 SEC，“Check SEC now”仍可手工强制检查。失败不会推进成功时间，会在下一次小时检查时重试。没有新 Filing 就不运行 RAG 或 LLM；有新 Filing 才启动 `ThesisDelta` workflow，并停在 Human Review。

浏览器还可以创建和列出 theses、导入和列出 disclosures、查看历史 runs，并重新打开待审核任务。自动生成的 `/docs` 页面记录同一套 HTTP API。

## 90 秒验证

先使用产品页面体验 Filing → Evidence → Review 的正常路径，再运行下面这一条确定性测试，验证不便通过手工操作演示的两项状态保证：

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

该场景会在 Human Review 暂停任务，关闭并使用同一个 SQLite 数据库重新创建 Workflow，以相同 run ID 恢复并提交 Thesis v2；随后它会在另一个任务暂停期间推进权威 thesis head，并验证旧任务的批准操作返回 HTTP 409。整个测试不会调用外部模型。

## 明确边界

- 自动 ingestion 有意只支持官方 SEC EDGAR submissions，不做新闻、社交媒体或公司 IR 网站爬虫；
- scheduler 只是一个每小时判断本地 due state、每 24 小时最多自动成功访问 SEC 一次的进程内 `asyncio` loop，不是分布式任务系统或通知服务；
- Qdrant 当前运行在进程内；SQLite 持久化 Workflow 和 Thesis 状态；
- 没有 portfolio management、valuation、Multi-Agent role、distributed scheduler 或 queue；
- 五条 query 的 eval 有意保持很小；不声称已有成本、throughput、p50、p95 或 production-readiness 数据。

## 开源协议

AgenticThesis 使用 [GNU General Public License v3.0](LICENSE) 开源。
