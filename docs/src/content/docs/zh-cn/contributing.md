---
title: 参与贡献
description: 在不削弱 AgenticThesis 证据与审核保证的前提下开发和验证项目。
---

## 开发环境

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

所有代码、注释和 Git commit message 必须使用英文。不要向 Git 提交密钥、用户研究资料、生成的缓存或本地数据目录。

## 变更纪律

- 将可执行代码、测试和 `pyproject.toml` 视为当前事实来源。
- 保持来源可定位的证据、反证、明确未知、Human Review、恢复、重放、不可变 snapshot 与版本冲突保护。
- 使用确定性代码处理解析、检索融合、校验和提交。
- 只有真实的第二个集成需要时才添加抽象。
- 公开引擎变更需增加聚焦的契约测试；工作流变更需按需覆盖恢复与完整性。
- 切勿声称未经测量的准确率、延迟、吞吐量或生产就绪程度。

## 验证代码与文档

安装一次文档工具：

```bash
npm --prefix docs install
```

然后运行两类契约检查：

```bash
.venv/bin/python scripts/export_openapi.py
git diff --exit-code -- docs/openapi.json
.venv/bin/pytest -q -p no:cacheprovider
npm --prefix docs run build
git diff --check
```

本地预览：

```bash
npm --prefix docs run dev
```

Starlight 启动后会打印本地预览 URL。FastAPI 产品仍使用 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

## 文档规则

- README 是仓库入口；运维与参考细节放在本站。
- 命令必须可执行；FastAPI route 或 model 变更后重新生成 `docs/openapi.json`，CI 会拒绝过期 schema。
- 架构边界变化时，同时更新可编辑 HTML 与渲染后的 SVG。
- 执行计划不进入公开导航。
- 英文仍是默认和权威文档语言；简体中文页面与两份精简 README 应在语义上保持一致。

请通过 [GitHub Issues](https://github.com/suvimatt/agentic-thesis/issues) 报告缺陷或提出聚焦的变更。
