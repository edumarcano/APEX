import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, AgentKey, AgentAvailabilityStatus } from '../types/telemetry'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'

function profile(
  key: AgentKey,
  status: AgentAvailabilityStatus = 'available',
  reason: string | null = null,
): AgentStatus {
  const mode = key === 'panthera' ? 'cloud' : 'local'
  return {
    key,
    display_name: `Apex ${key}`,
    description: 'Test profile.',
    configured_model: mode === 'cloud' ? 'test-cloud' : 'test-local',
    sort_order: 0,
    capabilities: [],
    native_tools: {},
    provider: mode === 'cloud' ? 'openai' : 'llama_cpp',
    version: '7.4',
    runtime: mode,
    tier: 'stable',
    stability: 'stable',
    model_stability: 'stable',
    effort_options: mode === 'cloud' ? ['light', 'focused', 'extended'] : null,
    default_effort: mode === 'cloud' ? 'focused' : null,
    context_window: null,
    context_window_options: null,
    context_window_high_resource_options: null,
    default_context_window: null,
    reasoning_mode: mode === 'local' ? 'none' : null,
    reasoning_mode_options: mode === 'local' ? ['none'] : null,
    default_reasoning_mode: mode === 'local' ? 'none' : null,
    status,
    status_source: mode === 'cloud' ? 'configuration' : 'runtime',
    status_checked_at: null,
    provider_account_tier: null,
    pricing: { currency: 'USD', pricing_version: 'test', billing_basis: mode === 'cloud' ? 'standard' : 'local', input_per_million: 0, output_per_million: 0, cached_input_per_million: 0, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null },
    active: false,
    loading: false,
    reason,
    idle_unload_remaining_seconds: null,
    loaded_model: null,
  }
}

const AVAILABLE_PROFILES = [
  profile('panthera'),
  profile('felis'),
]

function renderSelector(overrides: Partial<ComponentProps<typeof BriefingModeSelector>> = {}) {
  const props: ComponentProps<typeof BriefingModeSelector> = {
    value: 'panthera',
    onChange: vi.fn(),
    agents: AVAILABLE_PROFILES,
    hydrated: true,
    disabled: false,
    ...overrides,
  }
  return { ...render(<BriefingModeSelector {...props} />), props }
}

describe('BriefingModeSelector', () => {
  it('groups and describes cloud, local, and model-free modes', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByRole('button', { name: /briefing: apex panthera/i }))
    const listbox = screen.getByRole('listbox', { name: /select briefing mode/i })

    expect(screen.getByText('Briefing Synthesis')).toBeVisible()
    expect(screen.getByText('Select a mode for the next briefing.')).toBeVisible()
    expect(screen.getAllByLabelText('Panthera agent mark')).toHaveLength(2)
    expect(screen.getByLabelText('Structured Digest mark')).toBeVisible()
    expect(screen.getAllByText('No provider token charge')).toHaveLength(1)
    expect(screen.getByText('No model cost')).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Cloud' })).toBeInTheDocument()
    expect(within(listbox).getByRole('group', { name: 'Local' })).toBeInTheDocument()
    expect(within(listbox).getByText('Full briefing · GPT-5.6 Luna')).toBeVisible()
    expect(within(listbox).getByText('Full briefing · Gemma 4 E2B')).toBeVisible()
    expect(within(listbox).getByText('Structured facts · no model or synthesis')).toBeVisible()
    expect(within(listbox).queryByRole('option', { name: /^Mus\b/i })).not.toBeInTheDocument()
    expect(within(listbox).queryByRole('option', { name: /^Sorex\b/i })).not.toBeInTheDocument()
  })

  it('blocks unavailable model modes but always allows Structured Digest', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    renderSelector({
      onChange: onModeChange,
      agents: [
        profile('panthera'),
        profile('felis', 'insufficient_ram', 'Current memory pressure exceeds threshold'),
      ],
    })

    await user.click(screen.getByRole('button', { name: /briefing: apex panthera/i }))
    expect(screen.getByRole('option', { name: /felis/i })).toBeDisabled()

    await user.click(screen.getByRole('option', { name: /structured digest/i }))
    expect(onModeChange).toHaveBeenCalledWith('structured_digest')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderSelector()
    const trigger = screen.getByRole('button', { name: /briefing: apex panthera/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('shows the selected mode description rather than pricing while closed', () => {
    renderSelector()

    expect(screen.getByRole('button', { name: /briefing: apex panthera/i })).toHaveTextContent(/Full briefing/)
    expect(screen.getByRole('button', { name: /briefing: apex panthera/i })).not.toHaveTextContent(/In \$/)
  })
})

describe('BriefingGenerateControl', () => {
  it('keeps refresh-and-synthesize available when current-snapshot synthesis is disabled', async () => {
    const onGenerate = vi.fn()
    const onRefreshAll = vi.fn()
    const onRefreshAndGenerate = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingGenerateControl
        mainDisabled
        refreshDisabled={false}
        busy={false}
        onGenerate={onGenerate}
        onRefreshAll={onRefreshAll}
        onRefreshAndGenerate={onRefreshAndGenerate}
      />,
    )

    expect(screen.getByRole('button', { name: /synthesize briefing from current telemetry/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /more briefing synthesis options/i }))
    await user.click(screen.getByRole('menuitem', { name: /refresh all & synthesize/i }))

    expect(onGenerate).not.toHaveBeenCalled()
    expect(onRefreshAndGenerate).toHaveBeenCalledTimes(1)
  })

  it('offers refresh-only work from the synthesis menu', async () => {
    const onRefreshAll = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingGenerateControl
        mainDisabled={false}
        refreshDisabled={false}
        busy={false}
        onGenerate={vi.fn()}
        onRefreshAll={onRefreshAll}
        onRefreshAndGenerate={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: /more briefing synthesis options/i }))
    await user.click(screen.getAllByRole('menuitem')[0])

    expect(onRefreshAll).toHaveBeenCalledTimes(1)
  })

})
