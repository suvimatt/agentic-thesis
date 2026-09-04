<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/agentic-thesis/"><img src="https://img.shields.io/pypi/v/agentic-thesis.svg" alt="PyPI version"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-1C3C3C" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="AGPL-3.0 license"></a>
  <a href="https://github.com/suvimatt/agentic-thesis/stargazers"><img src="https://img.shields.io/github/stars/suvimatt/agentic-thesis?style=social" alt="GitHub stars"></a>
</p>

<h2 align="center">让每一份新的公司报告，都来挑战你的投资 Thesis</h2>

AgenticThesis 是一个开源 AI Agent，它用公司最新提交的正式报告，检验你的投资 Thesis（你为什么持有一只股票），并提供准确的原文引用、Human Review 和版本历史。

**它为所有关心股票背后公司生意的投资者而做——无论你采用哪种投资风格。**

你可以主要依靠公司研究，也可以同时参考价格走势、市场事件或其他方法。AgenticThesis 不要求你属于某个投资流派；它只专注于一件事：检查新的公司证据是在支持、削弱，还是推翻你写下的持股理由。

你写下这些理由，以及什么事实会证明每条理由错了。AgenticThesis 持续读取公司的正式报告，提出有证据的更新建议，并展示准确的报告原文。只有经过你的检查和批准，修改才会进入可追溯的 Thesis 版本历史。

> AgenticThesis 不只告诉你公司发生了什么；它说明新证据会怎样改变你的 Thesis，并要求你亲自批准这次改变。

> **当前状态：v1.0 alpha 开发中。** PyPI 最新发布版仍为 v0.9.0。

同一个 Python distribution 提供两个入口：

- `agentic-thesis serve` 使用 SQLite 和 embedded Qdrant 运行 self-host 应用；
- `AgenticThesisEngine` 是其他 Python 应用使用的受支持 interface。

### v1.0 alpha.1 到底升级了什么？

**v0.9 更像一个“财报阅读器”：你先给它一份报告，它再检查这份报告会不会影响你的持股理由。v1.0 alpha.1 开始把它变成一个会主动盯住公司向 SEC（美国证券监管机构）提交的新文件的雷达。**

- 它会记住上次检查到哪一份 SEC 文件，并在下一次检查时只处理新文件；即使那条旧记录已经被挤出最新列表，也能翻到历史页面接着找；
- 它不再只保存报告正文，还会原样保存 SEC 的文件目录页、正式报告、重要附件和机器可读的财务数据（XML），并记录文件来源、内容指纹和解析结果；
- 某个附件下载失败时，已经拿到的材料不会被丢掉；系统会明确告诉你缺了哪个附件、为什么失败；
- 每份新报告先由 Radar 决定怎么处理：有可读正文，就启动原有 Thesis workflow，逐条检查你的持股理由并等待 Human Review；没有可读正文，就只记录这次发现和原因，不强行让 AI 下结论。

换句话说，**v0.9 解决“读这份财报”，v1.0 alpha.1 新增的是“发现新报告、完整留档、判断要不要进入 Thesis 检查”这一整段前置流程。**

你先在 AgenticThesis 中写下：

- **这家公司的生意有哪些地方，让你愿意继续持有或关注它**；
- **出现什么事实，就说明这条理由错了**。

系统每天检查一次公司交给美国监管机构的正式报告。有新报告时，它逐条对照你保存的理由，展示相关原文，并请你确认是否更新记录。没有新报告时，就只记录本次检查，不花钱调用 AI 分析。

最终判断始终由你完成。AgenticThesis 不替你决定应该买入、卖出还是继续持有。

它只研究股票背后的公司生意：公司怎么赚钱、顾客为什么购买、产品怎么样、成本如何、优势在哪里，以及什么地方可能出问题。它不预测股价，也不判断今天的价格是便宜还是贵。

## 一个具体的 Apple 例子

较早一次真实 API 运行得到了下面这组 Apple 结果：

| 你原来的想法 | Apple 报告里的事实 | 结果 |
| --- | --- | --- |
| Apple 的服务业务能让公司从每笔销售中留下更多钱 | 服务业务每收到 100 美元，付完与这些销售直接有关的成本后，还剩 73.90 美元用于支付 Apple 的其他开支；硬件产品还剩 37.20 美元，服务销售额也增长了 13% | **目前看仍然对** |
| 大中华区的顾客会继续稳定购买 Apple 产品 | 当地销售额下降了 8%，主要因为人们购买的 iPhone 和 iPad 变少 | **现在可能不对了** |
| 即使某些零件只有很少的供应商，Apple 也能继续生产 | Apple 的一些零件仍然只来自一家或少数几家公司，但报告没有显示生产已经因此停下来 | **需要更谨慎** |

每个结果都能点回 Apple 报告里的完整原句。你没有批准之前，系统不会修改你保存的记录。

## 目录

- [一个具体的 Apple 例子](#一个具体的-apple-例子)
- [🚀 快速开始](#-快速开始)
- [Python Engine Interface](#python-engine-interface)
- [AgenticThesis 能帮你解决什么](#agenticthesis-能帮你解决什么)
- [项目里的几个名字](#项目里的几个名字)
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

最新发布版可用 `uvx agentic-thesis==0.9.0 serve` 启动。要运行当前 v1.0 alpha，请使用下面的开发安装步骤。

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。首次启动已经准备好一份 Apple 示例和两份公司报告。你保存的理由、原始资料、vector index、历史检查、待确认结果和已经批准的更新都会保存在 `~/.agentic-thesis/`，关闭并重新启动后仍可继续使用。

当前 `main` 使用全新的 v1.0 schema；它会拒绝所有 pre-v1.0 data directory，且不会修改旧数据。请使用新目录：

```bash
agentic-thesis serve --data-dir ~/.agentic-thesis-v10-alpha
```

在浏览器中输入公司名称、为什么持有或关注它的股票、这条理由为什么重要，以及一个能够证明这条理由错误的事实，即可添加新的公司，不需要理解 JSON 或内部 schema。

开发和确定性验证：

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

测试在适当位置使用确定性的检索和模型替代实现，因此不调用外部模型也能验证核心状态保证。

## Python Engine Interface

从 PyPI 安装 engine：

```bash
python -m pip install "agentic-thesis==0.9.0"
```

`open_local` 默认提供 SQLite checkpoint/state adapter 和可持久化的 embedded Qdrant index。调用者传入模型函数，并使用 `agentic_thesis` 导出的领域模型：

```python
from agentic_thesis import AgenticThesisEngine, ReviewDecision

engine = await AgenticThesisEngine.open_local(
    "./data",
    embed=embed,
    rerank=rerank,
    analyze=analyze,
)
await engine.create_thesis(thesis)
await engine.add_disclosure(disclosure)
paused = await engine.run(
    "aapl-2024-review",
    thesis.thesis_id,
    disclosure.document_id,
)
committed = await engine.review(
    "aapl-2024-review", ReviewDecision(action="approve")
)
revisions = await engine.list_revisions(thesis.thesis_id)
await engine.close()
```

`run` 返回类型化的 `ThesisRun`，其中包括绑定的 `disclosure_id`、校验后的 delta、evidence packs、审核结果，以及存在时的提交版本。`list_revisions` 只返回已批准并提交的 `ThesisRevision`；被拒绝的 run 保留在运行历史中，但不会成为 revision。

可执行 contract 见 [`tests/test_engine_contract.py`](tests/test_engine_contract.py)。FastAPI、浏览器页面、SSE 和本地 scheduler 都是同一个 engine 外面的 self-host adapter，engine 调用者不需要依赖这些入口。

## AgenticThesis 能帮你解决什么

| 常见问题 | AgenticThesis 的做法 |
| --- | --- |
| 每天被股价和新闻带着走，慢慢忘了当初为什么买入或继续持有 | 按时间保存你原来的理由 |
| 一份上百页的公司报告，很难逐条对照自己原来的想法 | 自动找到与每条理由最相关的内容 |
| AI 的回答听起来很肯定，却可能是编出来的 | 每个结论都校验并展示报告原文 |
| 新事实和自己的决定混在一起 | 只提出更新建议，等你确认后才保存 |
| 研究到一半关闭程序，回来又要从头开始 | 保存进度，重新启动后继续 |

这个产品帮助你检查自己的想法，不发出行动指令。报告里没有足够信息，或不同事实指向不同方向时，它会明确显示 **信息不足**，而不是硬猜答案。

## 项目里的几个名字

代码给几个日常概念起了简短的内部名字：

| 内部名字 | 日常含义 |
| --- | --- |
| Thesis | 你为什么持有或关注一只股票的理由记录 |
| Claim | 其中一条“这家公司以后还能做好”的具体理由 |
| Falsifier | 出现什么事实，就说明这条理由错了 |
| Thesis delta | 根据新报告提出的一次修改建议 |
| Human Review | 你亲自看报告原文，并决定是否保存修改 |

## 运行流程

```text
写下你为什么持有或关注这只股票，以及什么事实会证明每条理由错了
→ AgenticThesis 每天检查一次你指定的公司正式报告
→ 没有新报告：记录检查并停止
→ 有新报告：逐条对照它与原来保存的理由
→ 显示 目前看仍然对 / 需要更谨慎 / 现在可能不对了 / 信息不足
→ 每个结果都链接到准确的原文
→ 等你决定保持原记录，还是保存这次更新
```

系统内部把这四种结果存为 `supported`、`weakened`、`possibly_invalidated` 和 `unknown`。待确认的更新叫 `ThesisDelta`，持久化的运行记录叫 `ThesisRun`；你批准后，系统会同时创建下一个不可变的 `ThesisSnapshot` 和可查询的 `ThesisRevision`。

## 系统架构

[![AgenticThesis 系统架构](docs/agentic-thesis-architecture.svg)](docs/agentic-thesis-architecture.html)

系统只有一个由应用拥有的 Workflow，而不是一组自治 Agent。LangGraph 协调六个明确的状态迁移；确定性代码负责检索融合、Context 预算、引用完整性和版本提交，LLM 只负责条件式语义重排序和结构化 Thesis 比较。

| 边界 | 职责 | 实现 |
| --- | --- | --- |
| 证据采集 | 先把公司新交的正式文件原样保存，再交给 AI 解读 | 公司提交记录（disclosure event）、SEC 文件目录页、正式报告与附件的原始 bytes、SHA-256 内容指纹、解析结果、下载失败明细和每次检查记录 |
| 接口 | 管理 theses 和 disclosures、检查指定 SEC filing types、异步启动任务、重放进度并接受审核决定 | FastAPI、后台 `asyncio` tasks、durable SSE |
| 检索 | 在当前 run 绑定的 disclosure 中找到与 claim 相关的上下文 | 由完整句子、列表项和带上下文表格行组成的确定性结构化窗口；claim 和 falsifier query；BM25、本地持久化 Qdrant vector、RRF 和条件式 API rerank |
| Working Context | 为每条 claim 提供最小、充分、可定位来源的证据 | query-conditioned `EvidencePack`，在每条 claim 的 2,000-token 预算内装入完整 citation span，并保存绑定 span 的 evidence ID 和精确原文偏移 |
| 语义分析 | 只根据提供的证据比较每条 Thesis claim | API Structured Outputs → 类型化 `ThesisDelta` |
| 完整性门禁 | 阻止无依据结论和不安全状态变更 | 精确 citation-span/source 校验、falsifier 校验、exact-claim 校验、Human Review |
| 持久状态 | 恢复运行中或暂停的任务并保存权威 Thesis 历史 | canonical disclosures、LangGraph SQLite checkpoint、持久化 `ThesisRun` 与 events、不可变 `ThesisSnapshot`、可查询 `ThesisRevision`、thesis head |
| 提交 | 只有 base version 仍为当前版本时才能应用已批准的 delta | SQLite compare-and-swap → `vN+1` 或 `version_conflict` |

两份仓库内 SEC Filing 经结构化提取后共有 97,680 个 `cl100k_base` token。检索使用 223 个有界窗口提供上下文，但 citation 指向 2,547 个完整原子 span，并带有精确 canonical offset。模型调用不会接收完整 Filing，而只接收逐条 claim 构建、带引用的 `EvidencePack`。这使 **Context**（当前调用的临时工作证据）、**Memory**（版本化 Thesis）和 **Workflow State**（可恢复执行状态）彼此分离。

架构图的可编辑源文件是 [`docs/agentic-thesis-architecture.html`](docs/agentic-thesis-architecture.html)，README 展示其导出的 SVG。

## 已实现能力

- 自动读取 SEC 网页版公司报告，去掉藏在页面里、对阅读无用的机器标签，同时保留章节、完整句子、列表和表格结构；
- 每次发现新报告，都原样保存 SEC 文件目录页、正式报告、重要附件和机器可读的财务数据文件（XML/XBRL），并记录来源、文件类型、内容指纹和是否解析成功；
- 记住上次检查到哪一份报告；需要时会翻查 SEC 历史页面。某个附件下载失败也会单独留下失败记录，不会抹掉已经成功取得的材料；
- 每份新报告都会留下 Radar 结果：有可读内容则进入待审核流程（`needs_review`），没有则只记录发现（`digest`）；
- 由完整 citation span 组成、而不是按 token count 截断的有界 retrieval windows，带稳定 ID 和精确 canonical offset；
- claim 与 falsifier 共同检索：BM25 + 持久化 Qdrant vector retrieval 和 Reciprocal Rank Fusion；只有新增 window 才调用 embedding，且只有 BM25/vector top-1 不同且 top-3 交集少于 2 个 window 时才调用 listwise API reranking；
- 带硬性 token budget、完整 span 选择、来源覆盖和 retained evidence ID 的 extractive Context packing；
- 使用 OpenAI Structured Outputs 实现四态 `ThesisDelta` contract；
- 精确 span-to-source 引用校验；无依据或伪造 offset 的输出会降级为 `unknown`；
- 六节点 LangGraph、Human Review interrupt 和 SQLite checkpoint/resume；
- 不可变 Thesis snapshot 和 compare-and-swap 冲突保护；
- 一份 disclosure 对应一个 run 的执行模型、类型化并持久化的 `ThesisRun` 结果，以及可查询的已提交 `ThesisRevision` 历史；
- 可持久化的 run history，以及通过 `Last-Event-ID` 跨浏览器或服务重启重放的顺序化 SSE；
- 多个相互隔离的 theses，以及手工 HTML/TXT disclosure 导入；
- 每个 Thesis 可以盯住一家公司在 SEC 发布的新文件；你可以选择要看的报告类型，系统会识别重复文件，并支持手工立即检查和每日自动检查；
- 异步 FastAPI、后台任务、有界且带 timeout 的模型调用、停止服务后的 checkpoint 恢复，以及不暴露 chain-of-thought 的实时 LangGraph events；
- 无前端依赖的产品页面，提供 guided company-reason editor，并支持 disclosure 管理、进度、引用、Context 压缩和 Human Review；
- 可安装的 `agentic-thesis serve` CLI、package sample data 和稳定的用户数据目录。

## 验证结果

2026-09-04 在仓库内 fixture 上的观测结果：

| 检查项 | 观测结果 |
| --- | ---: |
| 测试 | 23 passed |
| Wheel build | passed |
| 2023 提取 tokens / retrieval windows | 48,777 / 111 |
| 2024 提取 tokens / retrieval windows | 48,903 / 112 |
| 原子 citation spans / 精确 offset 还原 | 2,547 / 100% |
| 分类 gold queries | 26：15 calibration / 11 held-out |
| 人工标注 Thesis delta cases | 4 条，覆盖 Apple、Microsoft 和全部四种状态 |
| BM25 / fake-vector / hybrid Recall@5 | 0.923 / 0.577 / 0.885 |
| always-rerank / conditional-rerank Recall@5 | 0.962 / 0.962 |
| BM25 / vector / hybrid / always / conditional MRR | 0.653 / 0.438 / 0.628 / 0.750 / 0.756 |
| Conditional rerank 调用 | 15 / 26 |
| held-out conditional Recall@5 / MRR | 1.00 / 0.720 |
| 伪造 quote 或 offset | 降级为 `unknown` |
| 重启与恢复 | 使用相同 run ID 提交 v2 |
| 旧版本写入 | 返回 `version_conflict` / HTTP 409 |

`evals/gold.json` 的 26 条 case 横跨两份 Apple filing，覆盖 lexical、numeric、semantic、risk 和 regulatory 检索问题。`evals/delta_gold.json` 的 4 条 case 覆盖 Apple、Microsoft 和全部四种 delta 状态，并包含 Apple 的连续两期 disclosure。确定性测试不调用外部模型，只验证数据集与检索 policy，不声称模型准确率。

仓库中的 `evals/live_results.json` 保留了较早一次覆盖两份 Filing、219 个旧版 chunks、5 条 query 的真实 API 运行，使用 `qwen3.7-text-embedding` 和 `gpt-5.6-luna`：

| Live 检查项 | 观测结果 |
| --- | ---: |
| BM25 / vector / hybrid / rerank Recall@5 | 1.00 / 0.80 / 1.00 / 1.00 |
| Gold 排名，hybrid → rerank | 2→2, 1→1, 2→2, 4→5, 3→3 |
| 压缩后保留 gold evidence | 5 / 5 |
| 校验后的 claim 状态 | supported / possibly_invalidated / weakened |
| Embedding index | 8.73 s |
| 五条 query rerank evaluation | 38.17 s |
| 三条 claim structured analysis | 16.18 s |

较早的 reranker 保住了 Recall@5，但没有改善 gold position，其中一条从第 4 降到第 5。这份报告早于 v0.9 结构化 chunking 和当前 26 条检索 evaluation，因此仅作为历史记录：目前不声称当前 live model quality。这些耗时只代表一次运行，不是 latency benchmark 或 production SLO。

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
  -d '{"run_id":"aapl-2024-review","thesis_id":"aapl-primary","disclosure_id":"aapl-2024"}'

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

第一次成功检查只导入最新一份符合条件的公司文件，并记住它的 SEC 唯一编号；不会突然把多年的旧报告全部塞进来。以后每次检查只寻找排在它之后的新文件；如果这条记录不在最新列表里，系统会继续翻查 SEC 历史页面。你可以通过 `/events`、`/artifacts`、`/collection-attempts` 和 `/radar` 查看发现了什么、保存了哪些原始文件、缺了哪些附件，以及为什么决定进入或跳过 Thesis 检查。检查失败时不会假装成功，也不会跳过下次重试；每份有可读正文的新报告都会单独启动一次 `ThesisDelta` workflow，并停在 Human Review 等你确认。

浏览器还可以创建和列出 theses、导入和列出 disclosures、查看历史 runs，并重新打开待审核任务。自动生成的 `/docs` 页面记录同一套 HTTP API。

## 90 秒验证

先使用产品页面体验 Filing → Evidence → Review 的正常路径，再运行下面这一条确定性测试，验证不便通过手工操作演示的两项状态保证：

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

该场景会在 Human Review 暂停任务，关闭并使用同一套本地持久化数据重新创建 Workflow，以相同 run ID 恢复并提交 Thesis v2；随后它会在另一个任务暂停期间推进权威 thesis head，并验证旧任务的批准操作返回 HTTP 409。业务状态与 LangGraph checkpoint 使用独立的 SQLite 文件，以避免写入锁竞争。整个测试使用确定性的 fake retrieval 与 analysis，不会调用外部模型。

## 明确边界

- v1.0 alpha.1 目前只会自动盯住 SEC EDGAR；公司官网的投资者关系（IR）页面、PDF/OCR、电话会文字稿和新闻线索还没有接入；
- scheduler 只是一个每小时判断本地 due state、每 24 小时最多自动成功访问 SEC 一次的进程内 `asyncio` loop，不是分布式任务系统或通知服务；
- Qdrant 以 embedded 模式运行，并把 vectors 持久化到用户数据目录；SQLite 持久化 Workflow 和 Thesis 状态；
- 不预测股价，不建议应该投入多少钱，也没有 Multi-Agent role、distributed scheduler 或 queue；
- 检索 gold set 包含 Apple 两份 filing 的 26 条问题；四条 Thesis delta case 已加入 Microsoft，但仍缺少更广的公司覆盖和一份已完成的当前 v1.0 alpha live API 结果；
- 没有实测 throughput、p50、p95 或 production-readiness 声明。

## 开源协议

AgenticThesis 使用 [GNU Affero General Public License v3.0](LICENSE) 开源。
