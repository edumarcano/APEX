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
  return {
    key,
    display_name: `Apex ${key}`,
    provider: key === 'comet' ? 'gemini' : 'ollama',
    tier: 'stable',
    stability: 'stable',
    status,
    active: false,
    loading: false,
    reason,
    idle_unload_remaining_seconds: null,
    loaded_model: null,
  }
}

const AVAILABLE_PROFILES = [
  profile('comet'),
  profile('lynx'),
  profile('acinonyx'),
  profile('neofelis'),
]

function renderSelector(overrides: Partial<ComponentProps<typeof BriefingModeSelector>> = {}) {
  const props: ComponentProps<typeof BriefingModeSelector> = {
    value: 'comet',
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

    await user.click(screen.getByRole('button', { name: /briefing mode: comet/i }))
    const listbox = screen.getByRole('listbox', { name: /select briefing mode/i })

    expect(screen.getByText('Briefing Synthesis')).toBeVisible()
    expect(screen.getByText('Select a mode for the next briefing.')).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Cloud' })).toBeInTheDocument()
    expect(within(listbox).getByRole('group', { name: 'Local' })).toBeInTheDocument()
    expect(within(listbox).getByText('Full briefing · fast cloud synthesis')).toBeVisible()
    expect(within(listbox).getByText('Full briefing · higher capacity, slower')).toBeVisible()
    expect(within(listbox).getByText('Structured facts · no model or synthesis')).toBeVisible()
  })

  it('blocks unavailable model modes but always allows Structured Digest', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    renderSelector({
      onChange: onModeChange,
      profiles: [
        profile('comet'),
        profile('lynx'),
        profile('acinonyx', 'insufficient_ram', 'Current memory pressure exceeds threshold'),
        profile('neofelis'),
      ],
    })

    await user.click(screen.getByRole('button', { name: /briefing mode: comet/i }))
    expect(screen.getByRole('option', { name: /acinonyx/i })).toBeDisabled()

    await user.click(screen.getByRole('option', { name: /structured digest/i }))
    expect(onModeChange).toHaveBeenCalledWith('structured_digest')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderSelector()
    const trigger = screen.getByRole('button', { name: /briefing mode: comet/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})

describe('BriefingGenerateControl', () => {
  it('keeps refresh-and-synthesize available when current-snapshot synthesis is disabled', async () => {
    const onGenerate = vi.fn()
    const onRefreshAndGenerate = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingGenerateControl
        mainDisabled
        refreshDisabled={false}
        busy={false}
        onGenerate={onGenerate}
        onRefreshAndGenerate={onRefreshAndGenerate}
      />,
    )

    expect(screen.getByRole('button', { name: /synthesize briefing from current telemetry/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /more briefing synthesis options/i }))
    await user.click(screen.getByRole('menuitem', { name: /refresh all & synthesize/i }))

    expect(onGenerate).not.toHaveBeenCalled()
    expect(onRefreshAndGenerate).toHaveBeenCalledTimes(1)
  })

})
