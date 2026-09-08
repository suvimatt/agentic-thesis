---
title: 快速开始
description: 安装 AgenticThesis、配置模型端点并运行自托管应用。
---

## 选择安装来源

日常使用请安装最新发布包：

```bash
python -m pip install agentic-thesis
```

已发布的软件包可能落后于 `main` 上的开发进度。要评估仓库中的当前实现：

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

不要从教程中复制旧版本号。请通过 [PyPI](https://pypi.org/project/agentic-thesis/) 查看最新发布版本，通过仓库历史查看尚未发布的行为。

## 配置模型端点

在 `~/.agentic-thesis/.env`，或启动应用的目录中创建 `.env` 文件：

```dotenv
# 推理与重排
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_MODEL=gpt-5-mini

# 嵌入
EMBEDDING_API_KEY=your-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_EMBEDDING_MODEL=text-embedding-3-small
AGENTIC_THESIS_EMBEDDING_BATCH_SIZE=1
AGENTIC_THESIS_EMBEDDING_MAX_TOKENS=256

# 仅 SEC 监控需要
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

使用默认 OpenAI API 时，`OPENAI_BASE_URL` 可省略。打包后的 CLI 需要其他模型与嵌入凭据。保守的嵌入批量和 token 默认值适用于限制较小的 OpenAI 兼容提供商；仅在验证提供商能力后再调高。SEC 要求自动化客户端表明身份，请使用真实的产品/姓名与联系邮箱。

## 启动应用

使用已发布的软件包：

```bash
agentic-thesis serve
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。默认数据目录为 `~/.agentic-thesis`；所选目录包含 Thesis 状态、运行历史、检查点、工件和嵌入式向量索引。

v1.1 有意从全新 schema 开始。请使用新的数据目录，不要使用早期或预发布版本创建的目录。

## 第一个证据闭环

1. 在浏览器中创建一家公司 Thesis。
2. 写下一条具体的 Claim，以及至少一个能证伪它的事实。
3. 手动添加一份披露，或配置 SEC/发行人 IR 监控。
4. 收集到新事件后打开 Radar Inbox。
5. 检查精确的来源证据，并批准、编辑或拒绝拟议更新。
6. 确认只有获批更新出现在修订历史中。

## 不调用外部 API 验证 checkout

```bash
.venv/bin/pytest -q -p no:cacheprovider
```

确定性测试套件会在适当位置替代外部检索和模型调用。它验证引擎的状态与证据契约，不衡量线上模型准确率。
