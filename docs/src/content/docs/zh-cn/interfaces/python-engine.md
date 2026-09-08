---
title: Python 引擎
description: 使用 AgenticThesisEngine 这一受支持的应用接口。
---

`AgenticThesisEngine` 是将 AgenticThesis 嵌入其他 Python 应用时受支持的接口。调用方提供三个有边界的模型函数；引擎负责本地状态、检索、工作流执行、审核和修订历史。

## 打开本地引擎

```python
from agentic_thesis import AgenticThesisEngine

engine = await AgenticThesisEngine.open_local(
    "./data",
    embed=embed,      # list[str] -> list[list[float]]
    rerank=rerank,    # query + chunks -> ordered chunk IDs
    analyze=analyze,  # thesis + evidence packs -> ThesisDelta
)
```

SQLite 保存应用状态和 LangGraph 检查点；嵌入式 Qdrant 保存可重建的向量索引。应用停止时必须关闭引擎：

```python
await engine.close()
```

## 让一份披露进入审核

```python
from agentic_thesis import (
    DisclosureDocument,
    ReviewDecision,
    ThesisClaim,
    ThesisSnapshot,
)

thesis = ThesisSnapshot(
    thesis_id="example",
    company="Example Inc.",
    version=1,
    claims=[
        ThesisClaim(
            claim_id="retention",
            statement="Customer retention remains durable.",
            rationale="Retention supports recurring cash generation.",
            falsifiers=["Renewal rates decline materially."],
        )
    ],
)
await engine.create_thesis(thesis)

document = DisclosureDocument(
    document_id="example-2026-q2",
    thesis_id=thesis.thesis_id,
    source_id="issuer-q2-results",
    source_date="2026-08-01",
    source_url="https://example.com/investors/q2-results",
    content="<html><body>Renewal rates remained stable.</body></html>",
)
await engine.add_disclosure(document)

paused = await engine.run(
    "example-2026-q2-review",
    thesis.thesis_id,
    document.document_id,
)
assert paused.status == "awaiting_review"

committed = await engine.review(
    paused.run_id,
    ReviewDecision(action="approve"),
)
revisions = await engine.list_revisions(thesis.thesis_id)
```

`run()` 会注册一项绑定单份披露的运行，并执行到 Human Review。若应用要自行控制流式执行，请调用 `start_run()` 并迭代 `execute_run()`。

## 摄取来源事件

手动输入 HTML/TXT 时使用 `add_disclosure()`。收集器应使用 `process_event()`，以原子方式保存类型化的 `DisclosureEvent`、其 `ArtifactInput`、抓取失败、Radar 决策和可选的运行注册。

公开 Pydantic 模型由 `agentic_thesis` 导出。可执行契约位于 [`tests/test_engine_contract.py`](https://github.com/suvimatt/agentic-thesis/blob/main/tests/test_engine_contract.py)；它比从旧版本复制的示例更可信。

## 冲突与失败

- 重复的 Thesis、披露、事件或运行标识会引发 `EngineConflictError`。
- 缺少 Thesis/披露/运行输入会引发 `ValueError`。
- 针对过期 Thesis head 的批准会引发 `EngineConflictError`，并保留两份历史。
- 不受支持或无效的证据会以失败/unknown 状态保留，不会静默消失。
