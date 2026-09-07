// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';

export default defineConfig({
  site: 'https://thesis.getsuvi.com/',
  integrations: [
    starlight({
      title: 'AgenticThesis',
      description: 'Evidence-guarded, versioned investment theses for long-term investors.',
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
        ]),
      ],
      sidebar: [
        { label: 'Overview', slug: 'index' },
        { label: 'Getting Started', slug: 'getting-started' },
        { label: 'Core Workflow', slug: 'core-workflow' },
        {
          label: 'Interfaces',
          items: [
            { label: 'Python Engine', slug: 'interfaces/python-engine' },
            { label: 'HTTP API and CLI', slug: 'interfaces/http-api-cli' },
          ],
        },
        ...openAPISidebarGroups,
        { label: 'Operations', slug: 'operations' },
        {
          label: 'Architecture & Quality',
          items: [
            { label: 'Architecture', slug: 'architecture' },
            { label: 'Evaluation & Limits', slug: 'evaluation' },
          ],
        },
        {
          label: 'Project',
          items: [
            { label: 'GetSuvi — Official Website', link: 'https://getsuvi.com/' },
            { label: 'Release Notes', slug: 'releases' },
            { label: 'Contributing', slug: 'contributing' },
            { label: 'License & Security', slug: 'project' },
          ],
        },
      ],
    }),
  ],
});
