---
title: 证据守护的投资 Thesis
description: 一个让投资 Thesis 始终有证据守护、经人工审核并保留版本的开源引擎。
tableOfContents: false
hero:
  title: 让新证据挑战你的投资 Thesis。
  tagline: 一个开源 AI Agent，用新的公司披露检验明确的投资 Thesis。每项拟议变更都链接到精确的来源证据，并在成为权威历史之前等待 Human Review。
  actions:
    - text: 5 分钟快速开始
      link: /zh-cn/getting-started/
      icon: right-arrow
    - text: 了解工作流
      link: /zh-cn/core-workflow/
      variant: secondary
    - text: 在 GitHub 查看
      link: https://github.com/suvimatt/agentic-thesis
      icon: external
      variant: minimal
---

:::note[v1.1.0 已发布]
[v1.1.0 已在 PyPI 发布](https://pypi.org/project/agentic-thesis/1.1.0/)。请使用全新的数据目录启动；不支持预发布版本的数据。
:::

## 适合谁

AgenticThesis 面向自主决策的长期投资者，以及希望自己的 Thesis 记录经得住新证据检验的开发者。你说明一家企业为何值得关注，以及哪些事实能推翻每条理由；引擎监控选定的官方来源，提出与证据关联的更新，并保留审核轨迹。

它也是一个可复用的后端引擎。同一个 Python 发行包同时提供 `AgenticThesisEngine` 接口和 `agentic-thesis serve` 自托管应用。

访问 [GetSuvi 官方网站](https://getsuvi.com/)了解 Suvi 更广泛的投资 Agent 产品家族后续进展。AgenticThesis 是其中开源的 Thesis Monitoring 引擎。

## 它负责什么

- 发现已配置的 SEC 与发行人 IR 事件；
- 保存带哈希和解析结果的不可变来源工件；
- 在使用模型前进行感知 Thesis 的 Radar 路由；
- 提供可定位到来源的证据与精确引用校验；
- 提供可恢复的运行、Human Review 与不可变 Thesis 修订。

AgenticThesis **不**负责证券估值、仓位规模、价格预测或买入/卖出/持有指令。最终判断属于投资者。

## 一个具体示例

一次早期的 Apple 实测将三条判断与一份新披露进行了比较：

| 已保存的判断 | 新公司证据 | 拟议结果 |
| --- | --- | --- |
| 服务业务改善 Apple 的商业经济性 | 服务业务毛利率仍显著高于产品，且服务收入增长 | 支持 |
| 大中华区需求保持稳定 | 大中华区销售额下降，主要由 iPhone 和 iPad 销售下滑导致 | 可能失效 |
| 供应商集中不会阻止生产 | 仍披露存在集中度，但没有证据表明生产已经停止 | 削弱 |

每项结果都保留了精确的来源证据。在获得批准前，任何结果都不会成为 Thesis 历史。这是一次说明性的历史运行，不构成投资建议，也不代表对 Apple 当前基本面的判断。

## 系统形态

[![AgenticThesis 架构](/agentic-thesis-architecture.svg)](/zh-cn/architecture/)

一个由应用自身拥有的 LangGraph 负责协调状态转换。确定性代码负责解析、检索融合、引用校验、Radar 路由和版本提交；模型仅用于嵌入、条件式重排和结构化 Thesis 比较。
