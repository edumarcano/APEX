export const MCP_PROVIDER_IDS = [
  'github',
  'brave',
  'alphavantage',
] as const

export type McpProviderId = (typeof MCP_PROVIDER_IDS)[number]

export interface McpProviderDefinition {
  id: McpProviderId
  label: string
  prerequisite: string
}

export const MCP_PROVIDERS: readonly McpProviderDefinition[] = [
  {
    id: 'github',
    label: 'GitHub',
    prerequisite: 'Read-only repository tools. Requires GITHUB_PERSONAL_ACCESS_TOKEN.',
  },
  {
    id: 'brave',
    label: 'Brave Search',
    prerequisite: 'Read-only web and news search. Requires BRAVE_API_KEY, Node.js, and npx.',
  },
  {
    id: 'alphavantage',
    label: 'Alpha Vantage',
    prerequisite: 'Read-only market research. Authorization opens through browser OAuth.',
  },
]
