// miAssist's manual (Docusaurus). Copied in shape from miForge's manual (docs/REUSE.md).
// Broken links and anchors THROW: a manual that builds with a dead link is not a passing build.
import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const SITE_URL = 'https://hitsainet.github.io';
const BASE_URL = '/miAssist/';

const config: Config = {
  title: 'miAssist Manual',
  tagline: 'One guide to the miStudio suite, whichever apps you have',
  favicon: 'img/favicon.svg',
  url: SITE_URL,
  baseUrl: BASE_URL,
  organizationName: 'hitsainet',
  projectName: 'miAssist',
  trailingSlash: false,
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },
  themes: ['@docusaurus/theme-mermaid'],
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/hitsainet/miAssist/tree/main/manual/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'miAssist Manual',
      logo: {alt: 'miAssist', src: 'img/logo.svg'},
      items: [
        {type: 'docSidebar', sidebarId: 'manualSidebar', position: 'left', label: 'Manual'},
        {to: '/connect', label: 'Connect', position: 'left'},
        {href: 'https://github.com/hitsainet/miAssist', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Manual',
          items: [
            {label: 'Quick start', to: '/'},
            {label: 'Connect', to: '/connect'},
            {label: 'Privacy', to: '/privacy'},
            {label: 'Troubleshooting', to: '/troubleshooting'},
          ],
        },
        {
          title: 'The suite',
          items: [
            {label: 'GitHub', href: 'https://github.com/hitsainet/miAssist'},
            {label: 'hitsai.net', href: 'https://hitsai.net'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Human in the Stream, LLC. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
