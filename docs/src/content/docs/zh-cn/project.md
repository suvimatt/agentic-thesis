---
title: 许可证与安全
description: 了解 AgenticThesis 的许可证、安全报告方式与投资用途边界。
---

## 许可证

AgenticThesis 使用 [GNU Affero General Public License v3.0](https://github.com/suvimatt/agentic-thesis/blob/main/LICENSE)（`AGPL-3.0-only`）。分发修改版本或通过网络提供服务前，请阅读许可证。

## 安全报告

不要在公开 issue 中披露凭据、投资者私有数据或可利用的漏洞。如果仓库提供 GitHub 私有漏洞报告入口，请使用该入口；否则通过 [GitHub](https://github.com/suvimatt) 链接的个人资料私下联系仓库所有者。

普通缺陷与功能请求请使用 [GitHub Issues](https://github.com/suvimatt/agentic-thesis/issues)。

## 信任边界

AgenticThesis 会处理不可信的 filing、发行人页面、上传文档和模型输出。其安全边界依赖于：

- 在解释前保存原始字节与 provenance；
- 将向量数据视为可重建索引，而不是权威状态；
- 校验精确的证据位置与引文；
- 在 Human Review 前保持模型输出非权威；
- 防止过期批准覆盖更新的 Thesis 历史；
- 以下载方式提供已保存工件，而不是让浏览器执行其内容。

## 投资边界

本项目维护公司基本面 Thesis。它不提供个性化投资建议，不判断公允价值，不决定仓位，也不决定买入、卖出或持有证券。来源证据可能不完整或错误，模型输出也可能出错，Human Review 始终是强制环节。
