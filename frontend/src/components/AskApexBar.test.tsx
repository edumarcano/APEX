import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type {
  AgentStatus,
  ToolCatalog,
  ToolPreflightEstimate,
} from '../types/telemetry'

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
  context_window: null,
  context_window_options: null,
  context_window_high_resource_options: null,
  default_context_window: null,
  reasoning_mode: 'none',
  reasoning_mode_options: ['none'],
  default_reasoning_mode: 'none',
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
  default_profile_name: 'No APEX Tools',
  default_selected_tool_names: [],
  provider_hosted_tools: [],
  context_window: 4096,
  reserved_response_tokens: 512,
}

const overflowPreflight: ToolPreflightEstimate = {
  agent: 'mus',
  selection: {
    requested_tool_names: ['get_weather_forecast'],
    offered_tool_names: ['get_weather_forecast'],
    rejected_tool_names: [],
    rejected_tools: [],
    selected_schema_tokens: 80,
    active_profile_id: 'custom_weather',
    active_profile_name: 'Weather',
  },
  breakdown: {
    system_instructions: 100,
    conversation_history: 200,
    hud_context: 0,
    selected_tool_schemas: 80,
    current_prompt: 5000,
    total: 5380,
    configured_context_window: 4096,
    reserved_response_tokens: 512,
    remaining_estimated_capacity: -1796,
    is_estimate: true,
  },
  warning: 'The generic token estimate exceeds the local context budget.',
  can_proceed: false,
}

function renderBar(
  onSubmit = vi.fn().mockResolvedValue(true),
  overrides: Partial<ComponentProps<typeof AskApexBar>> = {},
): ReturnType<typeof render> {
  return render(
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
  it('uses an icon-only tools trigger in Home', () => {
    renderBar(vi.fn(), { presentation: 'home' })

    const selector = screen.getByRole('button', { name: /Tools:/ })
    expect(selector).toHaveClass('size-8')
    expect(selector.textContent).toBe('')
  })

  it('keeps the tools summary text in Cortex', () => {
    renderBar()

    const selector = screen.getByRole('button', { name: /Tools:/ })
    expect(selector).toHaveTextContent('Tools')
    expect(selector).toHaveTextContent('Custom')
  })

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
    renderBar(onSubmit, { selectionReady: false, draftPrompt: 'Keep while hydrating' })

    const input = screen.getByLabelText('Ask APEX query')
    expect(input).toBeDisabled()
    expect(input).toHaveValue('Keep while hydrating')
    expect(screen.getByRole('button', { name: 'Send query' })).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('keeps the draft when the parent rejects the submission attempt', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    renderBar(onSubmit)

    const input = screen.getByLabelText('Ask APEX query')
    fireEvent.change(input, { target: { value: 'Keep this draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(input).toHaveValue('Keep this draft')
  })

  it('keeps the draft when the parent reports a catalog mismatch', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    renderBar(onSubmit, {
      catalog: { ...catalog, agent: 'panthera' },
    })

    const input = screen.getByLabelText('Ask APEX query')
    fireEvent.change(input, { target: { value: 'Wait for the active catalog' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(input).toHaveValue('Wait for the active catalog')
  })

  it('clears the draft exactly once after dispatch is accepted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const onDraftChange = vi.fn()
    renderBar(onSubmit, { onDraftChange })

    const input = screen.getByLabelText('Ask APEX query')
    fireEvent.change(input, { target: { value: 'Dispatch this draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))

    await waitFor(() => expect(input).toHaveValue(''))
    expect(onDraftChange).toHaveBeenLastCalledWith('')
    expect(onDraftChange).toHaveBeenCalledTimes(2)
  })

  it('keeps editing available but blocks a second send during submission preparation', () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    renderBar(onSubmit, { submissionPending: true })

    const input = screen.getByLabelText('Ask APEX query')
    expect(input).toBeEnabled()
    fireEvent.change(input, { target: { value: 'Wait for preparation' } })

    expect(input).toHaveValue('Wait for preparation')
    expect(screen.getByRole('button', { name: 'Preparing query' })).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('keeps the editor and selector usable while an overflow estimate blocks Send', () => {
    const onSubmit = vi.fn()
    const view = renderBar(onSubmit, { toolPreflight: overflowPreflight })

    const input = screen.getByLabelText('Ask APEX query')
    expect(input).toBeEnabled()
    expect(screen.getByRole('button', { name: /Tools:/ })).toBeEnabled()
    fireEvent.change(input, { target: { value: 'Shorten this prompt' } })

    expect(input).toHaveValue('Shorten this prompt')
    expect(screen.getByRole('button', { name: 'Send query' })).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()

    view.rerender(
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
        toolPreflight={null}
      />,
    )
    expect(screen.getByRole('button', { name: 'Send query' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Send query' }))
    expect(onSubmit).toHaveBeenCalledWith(
      'Shorten this prompt',
      'mus',
      ['get_weather_forecast'],
      'custom_weather',
    )
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
