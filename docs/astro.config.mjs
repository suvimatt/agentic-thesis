// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightOpenAPI, { createOpenAPISidebarGroup, openAPISidebarGroups } from 'starlight-openapi';

const unlistedChineseApiSidebarGroup = createOpenAPISidebarGroup();

export default defineConfig({
  site: 'https://thesis.getsuvi.com/',
  integrations: [
    starlight({
      title: 'AgenticThesis',
      description: 'Evidence-guarded, versioned investment theses for long-term investors.',
      locales: {
        root: { label: 'English', lang: 'en' },
        'zh-cn': { label: '简体中文', lang: 'zh-CN' },
      },
      customCss: ['./src/styles/custom.css'],
      editLink: {
        baseUrl: 'https://github.com/suvimatt/agentic-thesis/edit/main/docs/',
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/suvimatt/agentic-thesis',
        },
      ],
      plugins: [
        starlightOpenAPI([
          {
            base: 'api',
            schema: './openapi.json',
            sidebar: {
              label: 'API Reference',
              operations: { badges: true },
            },
          },
          {
            base: 'zh-cn/api',
            schema: './openapi.json',
            sidebar: {
              group: unlistedChineseApiSidebarGroup,
              operations: { badges: true },
            },
          },
        ]),
      ],
      sidebar: [
        { label: 'Overview', translations: { 'zh-CN': '概览' }, slug: 'index' },
        { label: 'Getting Started', translations: { 'zh-CN': '快速开始' }, slug: 'getting-started' },
        { label: 'Core Workflow', translations: { 'zh-CN': '核心工作流' }, slug: 'core-workflow' },
        {
          label: 'Interfaces',
          translations: { 'zh-CN': '接口' },
          items: [
            { label: 'Python Engine', translations: { 'zh-CN': 'Python 引擎' }, slug: 'interfaces/python-engine' },
            { label: 'HTTP API and CLI', translations: { 'zh-CN': 'HTTP API 与 CLI' }, slug: 'interfaces/http-api-cli' },
          ],
        },
        ...openAPISidebarGroups,
        { label: 'Operations', translations: { 'zh-CN': '运维' }, slug: 'operations' },
        {
          label: 'Architecture & Quality',
          translations: { 'zh-CN': '架构与质量' },
          items: [
            { label: 'Architecture', translations: { 'zh-CN': '架构' }, slug: 'architecture' },
            { label: 'Evaluation & Limits', translations: { 'zh-CN': '评估与局限' }, slug: 'evaluation' },
          ],
        },
        {
          label: 'Project',
          translations: { 'zh-CN': '项目' },
          items: [
            { label: 'GetSuvi — Official Website', translations: { 'zh-CN': 'GetSuvi — 官方网站' }, link: 'https://getsuvi.com/' },
            { label: 'Release Notes', translations: { 'zh-CN': '发布说明' }, slug: 'releases' },
            { label: 'Contributing', translations: { 'zh-CN': '参与贡献' }, slug: 'contributing' },
            { label: 'License & Security', translations: { 'zh-CN': '许可证与安全' }, slug: 'project' },
          ],
        },
      ],
    }),
  ],
});
