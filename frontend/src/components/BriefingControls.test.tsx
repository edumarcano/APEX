import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, AssistantProfile, ProfileAvailabilityStatus } from '../types/telemetry'
import { BriefingControls } from './BriefingControls'

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

function renderControls(overrides: Partial<ComponentProps<typeof BriefingControls>> = {}) {
  const props: ComponentProps<typeof BriefingControls> = {
    mode: 'comet',
    onModeChange: vi.fn(),
    profiles: AVAILABLE_PROFILES,
    profilesHydrated: true,
    activated: true,
    hasSnapshot: true,
    busy: false,
    onGenerate: vi.fn(),
    onRefreshAndGenerate: vi.fn(),
    ...overrides,
  }
  return { ...render(<BriefingControls {...props} />), props }
}

describe('BriefingControls', () => {
  it('groups and describes cloud, local, and model-free modes', async () => {
    const user = userEvent.setup()
    renderControls()

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
    renderControls({
      onModeChange,
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

  it('keeps refresh-and-generate available when no snapshot exists', async () => {
    const onGenerate = vi.fn()
    const onRefreshAndGenerate = vi.fn()
    const user = userEvent.setup()
    renderControls({ hasSnapshot: false, onGenerate, onRefreshAndGenerate })

    expect(screen.getByRole('button', { name: /generate briefing from current telemetry/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /more briefing generation options/i }))
    await user.click(screen.getByRole('menuitem', { name: /refresh all & generate/i }))

    expect(onGenerate).not.toHaveBeenCalled()
    expect(onRefreshAndGenerate).toHaveBeenCalledTimes(1)
  })

  it('keeps the selector available but hides Generate before activation', () => {
    const { rerender, props } = renderControls({ activated: false })
    expect(screen.getByRole('button', { name: /briefing mode/i })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /generate briefing from current telemetry/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /more briefing generation options/i })).not.toBeInTheDocument()

    rerender(<BriefingControls {...props} activated busy />)
    expect(screen.getByRole('button', { name: /briefing mode/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /generate briefing from current telemetry/i })).toBeDisabled()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderControls()
    const trigger = screen.getByRole('button', { name: /briefing mode: comet/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
