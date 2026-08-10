import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import McpSettingsSection from './McpSettingsSection'
import type { McpStatusState } from '../hooks/useMcpStatus'
import type { McpSettings } from '../types/settings'

const settings: McpSettings = {
  enabled: true,
  servers: {
    github: { enabled: true },
    brave: { enabled: false },
    alphavantage: { enabled: false },
  },
}

function buildRuntime(unavailable: boolean): McpStatusState {
  return {
    loading: false,
    unavailable,
    refresh: vi.fn(async () => undefined),
    status: {
      enabled: true,
      status: 'connected',
      reason: 'Connected.',
      servers: [
        {
          id: 'github',
          enabled: true,
          transport: 'http',
          status: 'connected',
          reason: 'Connected.',
          registered_tools: ['github_search_code'],
        },
      ],
    },
  }
}

describe('McpSettingsSection', () => {
  it('reports a status-service failure once without mislabeling providers', () => {
    const { rerender } = render(
      <McpSettingsSection
        sectionId="mcp-settings"
        baseline={settings}
        draft={settings}
        timing="Active"
        runtime={buildRuntime(true)}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/MCP status service unavailable/i)).toBeVisible()
    expect(screen.queryByText('Active runtime')).not.toBeInTheDocument()
    expect(screen.queryByText('Degraded')).not.toBeInTheDocument()

    rerender(
      <McpSettingsSection
        sectionId="mcp-settings"
        baseline={settings}
        draft={settings}
        timing="Active"
        runtime={buildRuntime(false)}
        onChange={vi.fn()}
      />,
    )

    expect(screen.queryByText(/MCP status service unavailable/i)).not.toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeVisible()
    expect(screen.getByText('github_search_code')).toBeVisible()
  })
})
