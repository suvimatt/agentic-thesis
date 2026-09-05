<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a> | <a href="https://thesis.getsuvi.com/">完整英文文档</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/agentic-thesis/"><img src="https://img.shields.io/pypi/v/agentic-thesis.svg" alt="PyPI 版本"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-1C3C3C" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="AGPL-3.0 协议"></a>
  <a href="https://github.com/suvimatt/agentic-thesis/stargazers"><img src="https://img.shields.io/github/stars/suvimatt/agentic-thesis?style=social" alt="GitHub stars"></a>
</p>

<h2 align="center">让每一份新的公司报告，都来挑战你的投资 Thesis。</h2>

AgenticThesis 是一个开源 AI Agent，用最新公司披露检验你的投资 Thesis——也就是你持有一只股票的理由；每个拟议变更都必须链接到精确原文，并在 Human Review 之后才能成为权威历史。

> **当前状态：** `main` 包含 v1.1 alpha 实现，PyPI 最新发布版可能落后于仓库。Alpha schema 升级会明确要求使用新的数据目录。

## 为什么需要它

你写下为什么一家企业值得继续持有或跟踪，以及哪些可观察事实会证明每个理由是错的。AgenticThesis 监控选定的 SEC 和公司 IR 来源，保留原始披露，找到与 Claim 相关的证据，并提出可审核的更新。

它不预测股价、不对证券估值、不决定仓位，也不提供买入、卖出或持有建议。最终判断始终属于投资者。

## 一个具体的 Apple 例子

一次较早的实测运行，把三个已保存的判断与 Apple 新财报进行了比较：

| 已保存的判断 | 公司新证据 | 拟议结果 |
| --- | --- | --- |
| Services 改善 Apple 的业务经济性 | Services 毛利率仍显著高于 Products，收入也在增长 | **仍获支持** |
| 大中华区需求保持稳定 | 大中华区销售下滑，主要来自 iPhone 和 iPad | **可能已失效** |
| 供应商集中不会中断生产 | 集中度风险仍存在，但报告没有证明生产已经中断 | **需要更谨慎** |

每个结果都保留了精确证据；未经批准，不会进入 Thesis 历史。这只是历史运行示例，不是投资建议，也不是对 Apple 当前基本面的判断。

## 快速开始

安装最新已发布版本：

```bash
python -m pip install agentic-thesis
```

在 `~/.agentic-thesis/.env` 中配置推理和 Embedding 端点：

```dotenv
OPENAI_API_KEY=your-key
AGENTIC_THESIS_MODEL=gpt-5-mini

EMBEDDING_API_KEY=your-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_EMBEDDING_MODEL=text-embedding-3-small

# 仅 SEC 监控需要
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

启动自托管应用：

```bash
agentic-thesis serve
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。如需体验当前 `main`：

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
.venv/bin/agentic-thesis serve --data-dir ~/.agentic-thesis-v11-alpha
```

模型 URL、SEC 配置和第一次证据循环请参阅[五分钟英文指南](https://thesis.getsuvi.com/getting-started/)。第一版完整技术文档以英文为权威版本。

## v1.1 alpha 已提供什么

- **权威采集：** SEC submissions 与明确可信的公司 IR 页面，包括重要 filing artifacts、PDF、演示文稿和官方文字稿。
- **不可变来源：** 原始 bytes、canonical URL、SHA-256、解析结果、下载失败以及精确页码/字符位置。
- **Thesis-aware Radar：** 在产生模型成本前，按版本化的确定性规则匹配 Claim 和 Falsifier。
- **有界证据：** 结构化 BM25/向量检索、条件重排、完整 span Context，以及精确引用校验。
- **人类拥有的历史：** 四状态结构化 Thesis Delta 在批准前始终不是权威历史。
- **可恢复执行：** checkpoint/resume、事件回放、不可变 revision 和 compare-and-swap 冲突保护。

## 架构

[![AgenticThesis 系统架构](docs/agentic-thesis-architecture.svg)](https://thesis.getsuvi.com/architecture/)

一个应用拥有的 LangGraph 负责协调工作流。确定性代码负责解析、检索融合、引用校验、Radar 路由和版本提交；模型只负责 Embedding、条件重排与结构化 Thesis 比较。

同一个 Python 包提供两个入口：

- `AgenticThesisEngine`：供 Python 应用集成；
- `agentic-thesis serve`：提供本地浏览器 UI 与 FastAPI 服务。

## 完整文档

- [开始使用](https://thesis.getsuvi.com/getting-started/)
- [核心工作流](https://thesis.getsuvi.com/core-workflow/)
- [Python Engine](https://thesis.getsuvi.com/interfaces/python-engine/)
- [HTTP API 与 CLI](https://thesis.getsuvi.com/interfaces/http-api-cli/)
- [运行与维护](https://thesis.getsuvi.com/operations/)
- [系统架构](https://thesis.getsuvi.com/architecture/)
- [评测与边界](https://thesis.getsuvi.com/evaluation/)

运行时 FastAPI `/docs` 页面始终是已安装版本的精确 endpoint/schema 参考。

## 边界与协议

AgenticThesis 只维护公司基本面 Thesis。估值、组合动作和投资决策不属于引擎。二手来源可以成为待核实线索，但不能独立授权 Thesis 历史。

项目采用 [GNU Affero General Public License v3.0](LICENSE)。Bug 和范围明确的提议请提交到 [GitHub Issues](https://github.com/suvimatt/agentic-thesis/issues)。

完整的证据、运行与贡献契约，
请查看[英文文档站](https://thesis.getsuvi.com/)。
