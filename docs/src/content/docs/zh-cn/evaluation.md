---
title: 评估与局限
description: 查看 AgenticThesis 可复现的检查、实测结果与明确不作出的声明。
---

## 当前确定性检查

以下结果基于仓库内 fixture。确定性测试套件于 2026-09-06 重新运行；检索指标记录于 2026-09-05：

| 检查 | 实测结果 |
| --- | ---: |
| 确定性测试用例 | Python 3.11 与 3.14 上均为 32 passed |
| Wheel 构建 | 通过 |
| 2023 / 2024 提取 token | 48,777 / 48,903 |
| 2023 / 2024 检索窗口 | 111 / 112 |
| 原子引用跨度 / 精确重建 | 2,547 / 100% |
| Gold 检索查询 | 26：15 个校准 / 11 个留出 |
| Thesis-delta 用例 | Apple 与 Microsoft 共 4 个；覆盖全部四种状态 |
| BM25 / fake-vector / hybrid Recall@5 | 0.923 / 0.577 / 0.885 |
| 始终 / 条件式重排 Recall@5 | 0.962 / 0.962 |
| 条件式重排调用次数 | 15 / 26 |
| 留出集条件式 Recall@5 / MRR | 1.00 / 0.720 |

这些数值来自仓库内评估数据和确定性替代实现。“fake-vector”结果不是嵌入提供商 benchmark。

运行可复现套件：

```bash
.venv/bin/pytest -q -p no:cacheprovider
```

聚焦的恢复/冲突场景：

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

## 历史线上结果

`evals/live_results.json` 保存了一次较早的、基于模型的五查询运行，数据来自 219 个旧版 chunk。它测得 hybrid 与 reranked Recall@5 均为 1.00，压缩后保留全部五项 gold evidence，并生成有效的结构化 Claim 状态。这次运行早于 v0.9 的结构感知 chunking 和当前 26 用例评估，因此只能作为历史证据。

使用已配置端点生成新的线上报告：

```bash
.venv/bin/python evals/run_live.py
```

脚本会更新 `evals/live_results.json`；提交前请检查 diff。单次运行不是延迟或准确率 benchmark。

## 完整性与恢复覆盖

确定性测试覆盖：

- 精确引文与偏移重建；
- 将伪造证据降级为 `unknown`；
- 重启后恢复到同一次运行；
- compare-and-swap 拒绝过期批准；
- 事件/Radar/运行标识的重放安全；
- 部分工件失败且不丢失数据；
- SEC amendment 关联与有边界的 IR 变化检测；
- 可定位到 PDF 页面的证据与明确的 OCR 限制。

## 明确的局限

- IR 发现止于已配置的 HTTPS 页面和相关的同域单跳链接。
- 没有通用爬虫、反机器人绕过、无头浏览器或音频转写。
- OCR 需要由引擎调用方提供函数；软件包不会下载模型。
- 尚未接入可靠的二手新闻。
- 调度只是一个进程内循环，不是队列或分布式服务。
- Gold 数据集仍然较小，且集中于少数发行人。
- 没有实测吞吐量、p50/p95 延迟、生产就绪、投资收益、价格预测、估值或仓位建议声明。
