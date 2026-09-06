# Documentation framework and hosting review

Verified 2026-09-05 against official project releases, documentation, and the
current AgenticThesis repository.

## Recommendation

1. **Do not turn the documentation site into a FastAPI application.** Keep the
   docs as static files served by Vercel's CDN.
2. **Do not deploy the current AgenticThesis runtime as a single Vercel
   Function.** FastAPI itself is supported, but the engine's local SQLite,
   checkpoint SQLite, embedded Qdrant, and process-local scheduler require a
   persistent, continuously running host.
3. **Material for MkDocs is no longer the long-term choice.** Its maintainers
   have put it into critical/security-fix-only maintenance and scheduled end of
   life for 2026-11-05. For a new site, **Astro Starlight is the strongest
   current replacement**. Migrate before publishing substantial custom
   theme work.
4. If a public trial is built later, keep the static docs and trial backend as
   separate deployable services. The trial can share a domain through routing,
   but it first needs durable external state adapters or a container/VM with a
   persistent disk.

## Framework comparison

| Stack | Current official release signal | Fit for this repository | Decision |
| --- | --- | --- | --- |
| MkDocs + Material | MkDocs core's latest release is [1.6.1, 2024-08-30](https://github.com/mkdocs/mkdocs/releases/tag/1.6.1). Material's latest release is [9.7.7, 2026-07-17](https://github.com/squidfunk/mkdocs-material/releases/tag/9.7.7), but that release explicitly says maintenance is limited to critical bug/security fixes and EOL is 2026-11-05. | Excellent Python/Markdown fit and the present site is already built, but the theme is now a near-term migration liability. | Do not invest further in it as the long-term site. |
| Astro Starlight | [`@astrojs/starlight` 0.42.0 was released 2026-09-02](https://github.com/withastro/starlight/releases/tag/%40astrojs%2Fstarlight%400.42.0). Its official overview includes navigation, search, i18n, SEO, typography, code highlighting, dark mode, Markdown/MDX, and accessibility-oriented defaults. | Adds a Node toolchain, but remains a documentation-focused static generator with the required features built in. It avoids a bespoke React application. | **Preferred replacement.** |
| VitePress | npm's stable tag is [`1.6.4`](https://registry.npmjs.org/vitepress/latest); its official release commit is dated 2025-08-05. Active development is on [`2.0.0-alpha.20`, released 2026-09-04](https://github.com/vuejs/vitepress/releases/tag/v2.0.0-alpha.20). It generates static HTML from Markdown and has [built-in browser-side local search](https://vitepress.dev/reference/default-theme-search). | Small and fast, but choosing it now means either an older stable line or a 2.0 alpha. Vue extensibility is unnecessary for the planned site. | Reconsider after VitePress 2 is stable. |
| Docusaurus | [`3.10.2` was released 2026-07-10](https://github.com/facebook/docusaurus/releases/tag/v3.10.2). Its official project scope includes docs, a blog, custom pages, localization, and a React-based customizable site. | Mature and active, but its React application surface, versioning/i18n/blog capabilities, and dependency footprint exceed the first-version requirements. | Viable, but overpowered here. |
| Zensical | Material's maintainers identify Zensical as its long-term successor; [`0.0.59` was released 2026-09-03](https://github.com/zensical/zensical/releases/tag/v0.0.59). | It may offer the lowest eventual migration cost for Material users, but the `0.0.x` version signals an interface that is not yet a conservative foundation. | Watch, do not adopt yet. |

Primary feature sources: [Starlight official overview](https://starlight.astro.build/),
[VitePress official overview](https://vitepress.dev/guide/what-is-vitepress), and
[Docusaurus official repository overview](https://github.com/facebook/docusaurus#readme).

No hosted documentation SaaS is needed. The requested navigation, search,
SEO, dark mode, previews, and custom domain are covered by a static generator
plus Vercel; a SaaS would add another account, pricing boundary, and migration
surface without solving a current requirement.

## Why one FastAPI deployment is the wrong boundary

Vercel officially supports Python ASGI/WSGI applications and detects FastAPI
entrypoints. It can also promote FastAPI-mounted static files to its CDN. A
FastAPI deployment becomes a **single Vercel Function**, with Fluid Compute
used by default ([Vercel FastAPI documentation](https://vercel.com/docs/frameworks/backend/fastapi)).
So serving the generated docs is technically possible, but it adds a dynamic
runtime to a static problem and does not make the AgenticThesis application
safe to run there.

The current engine assumes durable local files:

- `AgenticThesisEngine.open_local()` creates embedded Qdrant at
  `data_dir/qdrant` and application SQLite at
  `data_dir/agentic_thesis.sqlite` (`src/agentic_thesis/engine.py`).
- The workflow opens a second SQLite file for LangGraph checkpoints
  (`src/agentic_thesis/workflow.py`).
- The default FastAPI lifespan creates that directory, initializes the local
  engine, resumes runs, and starts a process-local monitoring task
  (`src/agentic_thesis/api.py`).
- The operations contract requires backing up and restoring the complete data
  directory (`docs/src/content/docs/operations.md`).

Those assumptions conflict with Vercel's execution topology:

- Vercel recommends persisting function writes to object storage rather than
  local files ([official file-use guide](https://vercel.com/kb/guide/how-can-i-use-files-in-serverless-functions)).
- Fluid Compute may run multiple invocations concurrently in one instance and
  scales instances dynamically; process/global state is therefore an
  optimization, not authoritative durable state
  ([Fluid Compute](https://vercel.com/docs/fluid-compute)).
- Function execution is bounded: the documented Fluid defaults/maxima are 300
  seconds on Hobby, 800 seconds on Pro/Enterprise, with a 1,800-second extended
  beta for supported runtimes. Vercel points unlimited-duration work toward
  Workflows ([Functions limits](https://vercel.com/docs/functions/limitations)).
- FastAPI shutdown cleanup receives at most 500 ms after `SIGTERM`, which is a
  weak match for closing local databases, canceling runs, and relying on an
  always-on polling loop ([FastAPI startup and shutdown on Vercel](https://vercel.com/docs/frameworks/backend/fastapi#startup-and-shutdown)).

Consequently, a one-function trial could lose or fork authoritative thesis
state across instances/deployments and cannot rely on the in-process poller to
run continuously. Fluid Compute improves concurrency and cold starts; it does
not turn local SQLite/Qdrant into shared durable storage.

## Minimal deployment shape

```text
thesis.getsuvi.com        static Starlight build on Vercel CDN
demo.thesis.getsuvi.com   later trial UI/API
                             -> persistent app database
                             -> persistent vector service
                             -> object storage for source artifacts
                             -> scheduled/durable worker
```

Vercel's Python documentation explicitly recommends **Services** when combining
a Python backend and frontend in one project, with each part built independently
and routed through a shared domain
([Python runtime](https://vercel.com/docs/functions/runtimes/python#combine-python-with-another-framework)).
That is the appropriate meaning of "one product on Vercel": one domain/project
experience, not one FastAPI process owning both static docs and durable agent
state.

## Decision trigger

- Migrate the existing pages to Starlight now if the site has not yet accrued
  meaningful custom work.
- Revisit Zensical after a stable release and documented Material migration
  path exist.
- Revisit a Vercel-hosted trial only after replacing `open_local()` persistence
  and the process-local monitor with durable service adapters and scheduled
  execution. Otherwise deploy the existing application unchanged to a
  persistent container/VM host instead.

## 2026-09-06 deployment verification

Yes: a Starlight site using Astro's default static output can use Vercel's
**Astro** framework preset (normally auto-detected) without
`@astrojs/vercel`. Starlight describes itself as an Astro integration and
links deployment guidance back to Astro; Astro and Vercel both state that a
static Astro site deploys to Vercel with zero extra configuration. The Vercel
adapter is needed only for on-demand rendering or optional Vercel runtime
features, not for this static documentation site.

- Build command: `npm run build` (the package script runs `astro build`).
- Output directory: `dist` (Astro's default).
- Vercel project Root Directory: `docs`, where `package.json` and
  `astro.config.mjs` live. This keeps the Astro build self-contained and the
  repository root focused on the Python service.
- Vercel should auto-detect Astro inside `docs`. If it does not, choose
  **Astro** explicitly; no custom build settings are needed.
- Remove the legacy MkDocs install/build/output overrides from `vercel.json`;
  otherwise they override the detected Astro preset. Keep the legacy `/docs`
  permanent redirects in `docs/vercel.json`.

Official sources:

- [Starlight: Getting Started](https://starlight.astro.build/getting-started/)
- [Astro: Deploy your Astro Site to Vercel](https://docs.astro.build/en/guides/deploy/vercel/)
- [Astro: general deploy settings](https://docs.astro.build/en/guides/deploy/#website-ui)
- [Vercel: Astro on Vercel](https://vercel.com/docs/frameworks/frontend/astro)
- [Vercel: configuring a build and Root Directory](https://vercel.com/docs/builds/configure-a-build#root-directory)
