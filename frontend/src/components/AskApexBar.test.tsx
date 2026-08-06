import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, ToolCatalog } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'

const mus: AgentStatus = {
  key: 'mus',
  display_name: 'Apex Mus',
  description: 'Balanced local profile.',
  configured_model: 'qwen3:4b-instruct',
  sort_order: 5,
  capabilities: ['Larger model'],
  native_tools: {},
  provider: 'ollama',
  version: '7.4',
  runtime: 'local',
  tier: 'balanced',
  stability: 'stable',
  effort_options: null,
  default_effort: null,
  status: 'available',
  status_source: 'runtime',
  status_checked_at: null,
  provider_account_tier: null,
  pricing: {
    currency: 'USD',
    pricing_version: '2026.08.02',
    billing_basis: 'local',
    input_per_million: 0,
    output_per_million: 0,
    cached_input_per_million: 0,
    long_context_threshold_tokens: null,
    long_context_input_per_million: null,
    long_context_output_per_million: null,
    long_context_cached_input_per_million: null,
  },
  active: false,
  loading: false,
  reason: null,
  idle_unload_remaining_seconds: null,
  loaded_model: null,
}

const catalog: ToolCatalog = {
  agent: 'mus',
  groups: [],
  tools: [],
  profiles: [],
  default_profile_id: 'no_tools',
  default_profile_name: 'No Tools',
  default_selected_tool_names: [],
  context_window: 4096,
  reserved_response_tokens: 512,
}

function renderBar(
  onSubmit = vi.fn(),
  overrides: Partial<ComponentProps<typeof AskApexBar>> = {},
): void {
  render(
    <AskApexBar
      presentation="cortex"
      activeAgent="mus"
      onSubmit={onSubmit}
      agentsStatus={[mus]}
      catalog={catalog}
      selectedToolNames={['get_weather_forecast']}
      activeToolProfileId="custom_weather"
      selectionReady
      isSubmitting={false}
      {...overrides}
    />,
  )
}

describe('AskApexBar unified tool selection', () => {
  it('submits the exact current names and profile ID', () => {
    const onSubmit = vi.fn()
    renderBar(onSubmit)

    fireEvent.change(screen.getByLabelText('Ask APEX query'), {
      target: { value: '  Check status  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onSubmit).toHaveBeenCalledWith(
      'Check status',
      'mus',
      ['get_weather_forecast'],
      'custom_weather',
    )
  })

  it('does not submit while the per-Agent selection is hydrating', () => {
    const onSubmit = vi.fn()
    renderBar(onSubmit, { selectionReady: false })

    const input = screen.getByLabelText('Ask APEX query')
    expect(input).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send query' })).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('has no slash-command compatibility path', () => {
    const onSubmit = vi.fn()
    renderBar(onSubmit)

    fireEvent.change(screen.getByLabelText('Ask APEX query'), {
      target: { value: '/weather tomorrow' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onSubmit).toHaveBeenCalledWith(
      '/weather tomorrow',
      'mus',
      ['get_weather_forecast'],
      'custom_weather',
    )
  })
})
