---
title: 发布说明
description: 跟踪当前已实现的 AgenticThesis 发布行为。
---

## v1.1.0

v1.1 将早期仅支持 SEC 的流程扩展为权威公司信息 Radar，并统一到一条可恢复的处理路径。

- 保存 SEC filing index、primary report、选定附件和 XML 数据及其哈希与解析结果。
- 遍历 SEC submission 历史，包含选定 form family 与 amendment；当报告期标识可确定时关联 amendment。
- 监控明确可信的发行人 IR HTML/feed 页面，以及相关的同域单跳报告、新闻稿、演示文稿和官方文字稿。
- 记录替换、移除、部分抓取失败、PDF 解析和有边界的选择性 OCR 状态。
- 在使用模型前，通过版本化的 Claim/Falsifier Radar 策略路由每个已接受事件。
- 原子提交来源工件、失败、Radar 和可选运行注册，标识支持安全重放。
- 经 Human Review 与 compare-and-swap Thesis 提交，保留精确页码/字符引用。
- 增加浏览器 Radar Inbox 与 SEC/IR 配置界面。
- 限制 OpenAI 兼容嵌入请求，明确报告模型超时，并注册检查点类型以支持严格恢复。
- 对规范化 IR 文本生成指纹，避免动态页面脚本制造重复披露。

v1.1.0 已发布到 [PyPI](https://pypi.org/project/agentic-thesis/1.1.0/)，带 tag 的源码与发布说明位于 [GitHub](https://github.com/suvimatt/agentic-thesis/releases/tag/v1.1.0)。请通过 [PyPI](https://pypi.org/project/agentic-thesis/) 查看最新发布包。

## 更早的里程碑

| 版本 | 确立的产品边界 |
| --- | --- |
| v1.0 alpha | 来源无关的事件/工件摄取、SEC 收集扩展、PDF、官方 IR 发现与 Radar |
| v0.9 | 结构感知的披露检索与精确引用跨度 |
| v0.8 | 每次运行绑定一份披露，包含 Human Review 与不可变历史的 Thesis 修订 |
| v0.7 | 公开 Python 引擎、自托管应用、检查点/恢复、SSE 重放与 CAS 提交 |

Git 历史与 tag 是权威的详细 changelog。仓库中的 v1.0 与 v1.1 内部执行记录有意不包含在公开文档构建中。
