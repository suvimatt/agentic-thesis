---
title: 核心工作流
description: 了解 Thesis、证伪条件、来源事件、Radar 决策、证据和 Human Review。
---

## 四个核心概念

| 术语 | 含义 |
| --- | --- |
| Thesis | 关于一家公司为何仍值得持有或关注的版本化记录 |
| Claim | Thesis 中一条可证伪的理由 |
| Falsifier | 会削弱或推翻 Claim 的可观察事实 |
| Thesis delta | 与证据关联、针对当前 Thesis 版本提出的更新 |

新的 Thesis 从版本 1 开始。每次分析运行都只绑定一份披露和一个基础 Thesis 版本。

## 从来源事件到审核

```text
已配置来源
  → 披露事件
  → 不可变来源工件
  → 已解析、可定位到来源的证据
  → 版本化 Radar 决策
  → 逐 Claim 的 Thesis delta
  → Human Review
  → 不可变 Thesis 修订
```

### 1. 收集来源

内置监控支持 SEC submissions，以及显式配置、由发行人拥有的 IR HTML/feed 页面。SEC 收集会保留 filing index、primary report、选定附件和 XML 数据。IR 发现仅限已配置的公开 HTTPS 页面，以及相关的同域单跳文档。

工件会在解释前保存。某个附件失败时，已成功收集的材料不会被丢弃，失败也会保持可见。

### 2. 通过 Radar 路由

Radar 在调用模型前作出确定性决策：

| 结果 | 含义 |
| --- | --- |
| `needs_review` | 权威且可解析的证据与某个 Claim 或 Falsifier 足够相关；注册分析运行 |
| `digest` | 保存并展示事件，但不消耗模型调用 |
| `ignored` | 记录路由决策，但不把事件提升到工作收件箱 |

记录会保留原因码、匹配的 Claim/Falsifier ID 和策略版本。重放同一事件不会生成重复的权威工作。

### 3. 构建证据

检索通过倒数排名融合，将确定性的 BM25 与本地 Qdrant 向量结果组合起来。只有当词法与向量排序的分歧达到阈值时，才调用条件式重排。Context packing 会在每个 Claim 的预算内保留完整引用跨度。

Evidence ID 可以解析到已保存的工件哈希、页码或精确字符范围，以及被引用的来源文本。伪造引用或无效偏移不能授权 Claim 更新。

### 4. 比较 Thesis

结构化比较使用四种状态：

- `supported`
- `weakened`
- `possibly_invalidated`
- `unknown`

当披露没有足够证据时，`unknown` 才是正确结果。避免编造结论并不是模型失败。

### 5. 让判断权属于人

工作流会暂停在 Human Review。批准会创建下一个不可变 `ThesisSnapshot` 和可查询的 `ThesisRevision`；拒绝会保留在运行历史中，但不会改变 Thesis。如果另一项审核已经推进了 Thesis head，compare-and-swap 保护会返回版本冲突，而不是覆盖更新的判断。

## 来源权威性

当精确证据可用时，监管机构与发行人来源可以支持 Thesis delta。用户提供的文档会保留明确来源。二手新闻只能作为 Radar 中的验证线索，不能独立成为权威 Thesis 历史。
