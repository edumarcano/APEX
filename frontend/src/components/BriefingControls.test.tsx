import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, AssistantProfile, ProfileAvailabilityStatus } from '../types/telemetry'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'

function profile(
  key: AssistantProfile,
  status: ProfileAvailabilityStatus = 'available',
  reason: string | null = null,
): AgentProfileStatus {
  const mode = key === 'sorex' || key === 'mus' ? 'local' : 'cloud'
  return {
    key,
    display_name: `Apex ${key}`,
    description: 'Test profile.',
    configured_model: mode === 'cloud' ? 'test-cloud' : 'test-local',
    sort_order: 0,
    capabilities: [],
    native_tools: {},
    provider: mode === 'cloud' ? 'openai' : 'ollama',
    version: '2.0',
    mode,
    tier: 'stable',
    stability: 'stable',
    effort_options: mode === 'cloud' ? ['light', 'focused', 'extended'] : null,
    default_effort: mode === 'cloud' ? 'focused' : null,
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
  profile('sorex'),
  profile('mus'),
]

function renderSelector(overrides: Partial<ComponentProps<typeof BriefingModeSelector>> = {}) {
  const props: ComponentProps<typeof BriefingModeSelector> = {
    value: 'panthera',
    onChange: vi.fn(),
    profiles: AVAILABLE_PROFILES,
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

    await user.click(screen.getByRole('button', { name: /briefing: panthera/i }))
    const listbox = screen.getByRole('listbox', { name: /select briefing mode/i })

    expect(screen.getByText('Briefing Synthesis')).toBeVisible()
    expect(screen.getByText('Select a mode for the next briefing.')).toBeVisible()
    expect(screen.getAllByLabelText('Panthera profile mark')).toHaveLength(2)
    expect(screen.getByLabelText('Structured Digest mark')).toBeVisible()
    expect(screen.getAllByText('No provider token charge')).toHaveLength(2)
    expect(screen.getByText('No model cost')).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Cloud' })).toBeInTheDocument()
    expect(within(listbox).getByRole('group', { name: 'Local' })).toBeInTheDocument()
    expect(within(listbox).getByText('Full briefing · cloud synthesis')).toBeVisible()
    expect(within(listbox).getByText('Full briefing · balanced local synthesis')).toBeVisible()
    expect(within(listbox).getByText('Structured facts · no model or synthesis')).toBeVisible()
  })

  it('blocks unavailable model modes but always allows Structured Digest', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    renderSelector({
      onChange: onModeChange,
      profiles: [
        profile('panthera'),
        profile('sorex'),
        profile('mus', 'insufficient_ram', 'Current memory pressure exceeds threshold'),
      ],
    })

    await user.click(screen.getByRole('button', { name: /briefing: panthera/i }))
    expect(screen.getByRole('option', { name: /mus/i })).toBeDisabled()

    await user.click(screen.getByRole('option', { name: /structured digest/i }))
    expect(onModeChange).toHaveBeenCalledWith('structured_digest')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderSelector()
    const trigger = screen.getByRole('button', { name: /briefing: panthera/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('shows the selected mode description rather than pricing while closed', () => {
    renderSelector()

    expect(screen.getByRole('button', { name: /briefing: panthera/i })).toHaveTextContent(/Full briefing/)
    expect(screen.getByRole('button', { name: /briefing: panthera/i })).not.toHaveTextContent(/In \$/)
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
