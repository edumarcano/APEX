import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ToolCatalog } from '../types/telemetry'

import { ToolsSelector } from './ToolsSelector'

const catalog: ToolCatalog = {
  agent: 'panthera',
  groups: [
    {
      id: 'schedule',
      label: 'Schedule',
      kind: 'apex_family',
      tool_count: 2,
      schema_token_subtotal: 180,
      tools: [
        {
          name: 'get_upcoming_calendar_events',
          label: 'Calendar events',
          description: 'Calendar',
          origin: 'native',
          source_id: 'apex',
          apex_family: 'schedule',
          risk: 'read',
          available: true,
          unavailable_reason: null,
          estimated_schema_tokens: 90,
          allowed_for_agent: true,
        },
        {
          name: 'get_active_reminders',
          label: 'Reminders',
          description: 'Reminders',
          origin: 'native',
          source_id: 'apex',
          apex_family: 'schedule',
          risk: 'read',
          available: true,
          unavailable_reason: null,
          estimated_schema_tokens: 90,
          allowed_for_agent: true,
        },
      ],
    },
    {
      id: 'github',
      label: 'GitHub',
      kind: 'mcp_server',
      tool_count: 1,
      schema_token_subtotal: 0,
      tools: [
        {
          name: 'github_search_code',
          label: 'Search code',
          description: 'Unavailable',
          origin: 'mcp',
          source_id: 'github',
          apex_family: null,
          risk: 'read',
          available: false,
          unavailable_reason: 'MCP server is disconnected.',
          estimated_schema_tokens: 0,
          allowed_for_agent: true,
        },
      ],
    },
  ],
  tools: [],
  profiles: [
    {
      id: 'no_tools',
      name: 'No APEX Tools',
      description: 'None',
      tool_names: [],
      built_in: true,
      dynamic: false,
    },
    {
      id: 'all_allowed',
      name: 'All APEX Tools',
      description: 'All',
      tool_names: [],
      built_in: true,
      dynamic: true,
    },
  ],
  default_profile_id: 'no_tools',
  default_profile_name: 'No APEX Tools',
  default_selected_tool_names: [],
  provider_hosted_tools: ['google_search'],
  context_window: 4096,
  reserved_response_tokens: 512,
}

function renderSelector(
  selectedToolNames: string[] = [],
  onSelectionChange = vi.fn(),
): void {
  render(
    <ToolsSelector
      catalog={catalog}
      selectedToolNames={selectedToolNames}
      activeToolProfileId={null}
      onSelectionChange={onSelectionChange}
      onProfileChange={vi.fn()}
    />,
  )
}

describe('ToolsSelector', () => {
  it('selects all available tools when an APEX family is toggled', async () => {
    const onSelectionChange = vi.fn()
    const user = userEvent.setup()
    renderSelector([], onSelectionChange)

    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    await user.click(screen.getByRole('checkbox', { name: 'Select Schedule' }))

    expect(onSelectionChange).toHaveBeenCalledWith([
      'get_upcoming_calendar_events',
      'get_active_reminders',
    ])
  })

  it('keeps unavailable MCP tools visible and disabled with a reason', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    await user.click(screen.getByRole('button', { name: 'Expand GitHub' }))
    const checkbox = screen.getByRole('checkbox', { name: /Search code/ })
    expect(checkbox).toBeDisabled()
    expect(screen.getByText('MCP server is disconnected.')).toBeInTheDocument()
  })

  it('lets a checked unavailable tool be removed and exposes orphaned names', async () => {
    const onSelectionChange = vi.fn()
    const user = userEvent.setup()
    renderSelector(['github_search_code', 'orphaned_tool'], onSelectionChange)

    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    await user.click(screen.getByRole('button', { name: 'Expand GitHub' }))
    const checkbox = screen.getByRole('checkbox', { name: /Search code/ })
    expect(checkbox).toBeEnabled()
    await user.click(checkbox)
    expect(onSelectionChange).toHaveBeenCalledWith(['orphaned_tool'])
    expect(screen.getByRole('region', { name: 'Unavailable selected tools' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove unavailable' }))
    expect(onSelectionChange).toHaveBeenLastCalledWith([])
  })

  it('applies a built-in profile through the profile selector', async () => {
    const onProfileChange = vi.fn()
    const user = userEvent.setup()
    render(
      <ToolsSelector
        catalog={catalog}
        selectedToolNames={[]}
        activeToolProfileId={null}
        onSelectionChange={vi.fn()}
        onProfileChange={onProfileChange}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Tool profile' }), 'all_allowed')
    expect(onProfileChange).toHaveBeenCalledWith('all_allowed')
  })

  it('shows profile and preflight API failures inside the selector', async () => {
    const user = userEvent.setup()
    render(
      <ToolsSelector
        catalog={catalog}
        selectedToolNames={[]}
        activeToolProfileId={null}
        onSelectionChange={vi.fn()}
        onProfileChange={vi.fn()}
        profileError="Profile request failed."
        preflightError="Tool estimate unavailable."
      />,
    )

    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    expect(screen.getByText(/Provider-hosted grounding active separately: Google Search/)).toBeInTheDocument()
    expect(screen.getByText('Profile request failed.')).toBeInTheDocument()
    expect(screen.getByText('Tool estimate unavailable.')).toBeInTheDocument()
  })
})
