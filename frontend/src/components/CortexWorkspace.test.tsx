import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { CortexWorkspace } from './CortexWorkspace'
import type { AgentProfileStatus } from '../types/telemetry'

const panthera: AgentProfileStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.',
  configured_model: 'gpt-5.6-luna', native_tools: {}, provider: 'openai', version: '2.0',
  mode: 'cloud', tier: 'balanced', stability: 'stable', effort_options: ['light', 'focused', 'extended'],
  default_effort: 'focused', status: 'available', active: false, loading: false, reason: null,
  idle_unload_remaining_seconds: null, loaded_model: null,
}

const neofelis: AgentProfileStatus = {
  ...panthera,
  key: 'neofelis',
  display_name: 'Apex Neofelis',
  configured_model: 'gemini-3.6-flash',
  provider: 'gemini',
  native_tools: { google_search: true, google_maps: true },
}

const acinonyx: AgentProfileStatus = {
  ...neofelis,
  key: 'acinonyx',
  display_name: 'Apex Acinonyx',
  configured_model: 'gemini-3.5-flash-lite',
}

function workspaceProps(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}): ComponentProps<typeof CortexWorkspace> {
  return {
    activeProfile: 'panthera', cloudEffort: 'focused', devModeActive: false, askApexEnabled: true,
    profilesStatus: [panthera], profilesStatusHydrated: true, history: [], latestTrace: [], error: null,
    contextUsage: { estimated_prompt_tokens: 45, peak_prompt_tokens: null, context_window: 4096, history_messages_dropped: 0 },
    isQuerying: false, snapshotAttached: true, snapshotAvailable: true,
    onSnapshotAttachedChange: vi.fn(), onProfileChange: vi.fn(), onModeChange: vi.fn(),
    onEffortChange: vi.fn(), onGoogleSearchChange: vi.fn(), neofelisGoogleSearchEnabled: true,
    onGoogleMapsChange: vi.fn(), neofelisGoogleMapsEnabled: true,
    onDelphinusXSearchChange: vi.fn(), delphinusXSearchEnabled: true,
    onOrcinusXSearchChange: vi.fn(), orcinusXSearchEnabled: true,
    onSubmit: vi.fn(), onNewSession: vi.fn(),
    ...overrides,
  }
}

describe('CortexWorkspace', () => {
  it('keeps runtime controls, context diagnostics, and new-session reset available together', async () => {
    const onNewSession = vi.fn()
    const onSnapshotAttachedChange = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ onNewSession, onSnapshotAttachedChange })} />)

    expect(screen.getByRole('region', { name: 'Cortex workspace' })).toBeInTheDocument()
    expect(screen.getByText('45/4,096')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /new session/i }))
    expect(onNewSession).toHaveBeenCalledOnce()
    await user.click(screen.getByRole('checkbox'))
    expect(onSnapshotAttachedChange).toHaveBeenCalledWith(false)
  })

  it('keeps the conversation canvas before the right-side inspector and exposes one card selector', () => {
    render(<CortexWorkspace {...workspaceProps()} />)

    const workspace = screen.getByRole('region', { name: 'Cortex workspace' })
    const inspector = screen.getByLabelText('Cortex inspector')
    expect(inspector.className).toContain('lg:border-l')
    expect(inspector.previousElementSibling).toHaveTextContent('Cortex is ready')
    expect(workspace.querySelectorAll('[aria-label="Profile selector"]')).toHaveLength(1)
    expect(screen.getByLabelText('Using Panthera')).not.toHaveAttribute('role', 'button')
  })

  it('shows development cards first and exposes only Neofelis grounding controls', () => {
    render(<CortexWorkspace {...workspaceProps({ activeProfile: 'neofelis', devModeActive: true, profilesStatus: [acinonyx, panthera, neofelis] })} />)

    const cards = screen.getAllByRole('button', { name: /use (acinonyx|panthera|neofelis)/i })
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual([
      'Use Acinonyx',
      'Use Panthera',
      'Use Neofelis',
    ])
    expect(screen.getByText('Powered by Gemini 3.6 Flash')).toBeInTheDocument()
    expect(screen.getAllByLabelText('Neofelis profile mark')).toHaveLength(2)
    expect(screen.getByRole('checkbox', { name: 'Google Search grounding' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Google Maps grounding' })).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: 'X Search grounding' })).not.toBeInTheDocument()
  })

  it.each([
    ['delphinus', 'Delphinus grounding', 'Grok 4.3'],
    ['orcinus', 'Orcinus grounding', 'Grok 4.5'],
  ] as const)('shows X Search only for %s', (activeProfile, groundingLabel, model) => {
    render(<CortexWorkspace {...workspaceProps({ activeProfile, profilesStatus: [{ ...panthera, key: activeProfile, display_name: `Apex ${activeProfile}`, provider: 'xai' }] })} />)

    expect(screen.getByLabelText(groundingLabel)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'X Search grounding' })).toBeChecked()
    expect(screen.getByText(`Powered by ${model}`)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Google Search grounding' })).not.toBeInTheDocument()
  })

  it('changes grounding preferences without changing the active request state', async () => {
    const onGoogleMapsChange = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ activeProfile: 'neofelis', isQuerying: true, profilesStatus: [neofelis], onGoogleMapsChange })} />)

    await user.click(screen.getByRole('checkbox', { name: 'Google Maps grounding' }))
    expect(onGoogleMapsChange).toHaveBeenCalledWith(false)
    expect(screen.getByText('Apex Neofelis working')).toBeInTheDocument()
  })
})
