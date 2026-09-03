# AGENTS.md

Repository guidance for coding agents. Treat executable code, tests, and `pyproject.toml` as the source of truth; verify them before relying on planning documents or old session context.

## Mission and Product Boundary

AgenticThesis is an open-source, stateful Python engine that helps self-directed, long-term investors track how new company disclosures support, weaken, or invalidate explicit company-fundamentals theses. Its promise is: **Your investment thesis, evidence-guarded and versioned by AI.** Every proposed change must remain traceable to source evidence and require Human Review before it becomes authoritative thesis history.

- AgenticThesis maintains company-fundamentals theses. Valuation, position sizing, and Buy/Sell/Hold decisions remain outside the engine and owned by the investor.
- Build a formal developer-facing engine, not a demo. Prioritize correctness, provenance, evaluation, extensibility through real use cases, and reliable self-hosting.
- AgenticThesis itself is supposed to be the underlying backend tech engine for investing that can be reused by others, and is not aiming to be an independent commercial product and brand itself, unless the repository scope is explicitly changed.

## Product Shape

- Keep one repository and one Python distribution with two entry points: the public `AgenticThesisEngine` interface and the `agentic-thesis serve` self-hosted application.
- Keep SQLite and embedded persistent Qdrant as the default local adapters. Add an abstraction only when a second real integration requires it.
- Keep one application-owned LangGraph workflow. Split agents or subgraphs only when they have genuinely distinct state, tools, schemas, or acceptance criteria.
- Support both user-supplied disclosures and scheduled SEC collection. Automatic collection becomes due 24 hours after the last successful check; only a new disclosure starts RAG/LLM thesis maintenance, which pauses at Human Review.

## Engineering Invariants

- Store critical state in explicit Pydantic models and durable application-owned storage, never only in prompts or chat history.
- Preserve source-addressable evidence, exact quotes, citation validation, counter-evidence, and explicit unknowns. Unsupported model output must not become an authoritative claim.
- Use deterministic code for parsing, chunking, retrieval fusion, validation, and version commits. Limit model work to embeddings, conditional reranking, and structured thesis comparison.
- Preserve checkpoint/resume, replayable events, immutable thesis snapshots, Human Review, and compare-and-swap version-conflict protection.
- Measure retrieval or model changes against versioned evaluation data. Publish only results produced by reproducible runs.

## Working Agreement

1. Inspect the working tree and the affected code, tests, configuration, and public interfaces before editing. Preserve unrelated user changes.
2. Prefer the smallest complete change; reuse existing seams and avoid speculative providers, plugins, services, or placeholder directories.
3. Add or update focused tests for changed behavior. Public engine changes require contract coverage; workflow-state changes require recovery, citation, review, and conflict-path coverage as applicable.
4. Keep `README.md` and `README_ZH.md` aligned for public behavior. When architecture boundaries change, update `docs/agentic-thesis-architecture.html` and its rendered SVG.
5. Run the narrowest relevant validation and report its actual result. Never claim unmeasured accuracy, latency, throughput, or production readiness.

All code, comments, and git commit messages must be in English. Do not commit secrets, private investor data, generated caches, or unrelated artifacts.
