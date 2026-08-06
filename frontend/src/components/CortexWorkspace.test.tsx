import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CortexWorkspace } from './CortexWorkspace'
import type { AgentStatus, LocalCommandStatus } from '../types/telemetry'

const panthera: AgentStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.', configured_model: 'gpt-5.6-luna', sort_order: 1, capabilities: ['Generalist', 'Planning'], native_tools: {}, provider: 'openai', version: '7.4', runtime: 'cloud', tier: 'balanced', stability: 'stable', effort_options: ['light', 'focused', 'extended'], default_effort: 'focused', status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: 0.02, long_context_threshold_tokens: 272000, long_context_input_per_million: 0.4, long_context_output_per_million: 1.8, long_context_cached_input_per_million: 0.04 }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}
const neofelis: AgentStatus = { ...panthera, key: 'neofelis', display_name: 'Apex Neofelis', configured_model: 'gemini-3.6-flash', provider: 'gemini', sort_order: 2, capabilities: ['Research', 'Google Search', 'Google Maps'], native_tools: { google_search: true, google_maps: true } }
const acinonyx: AgentStatus = { ...neofelis, key: 'acinonyx', display_name: 'Apex Acinonyx', configured_model: 'gemini-3.5-flash-lite', sort_order: 0, capabilities: ['Privacy sandbox', 'Masked context'], pricing: { ...neofelis.pricing, billing_basis: 'free_tier', input_per_million: 0, output_per_million: 0 } }
const mus: AgentStatus = { ...panthera, key: 'mus', display_name: 'Apex Mus', configured_model: 'qwen3:4b-instruct', provider: 'ollama', runtime: 'local', sort_order: 5, capabilities: ['Larger model', 'Primary local'], effort_options: null, default_effort: null, status: 'available', status_source: 'runtime', active: false, pricing: { ...panthera.pricing, billing_basis: 'local', input_per_million: 0, output_per_million: 0 } }
const apodemus: AgentStatus = { ...mus, key: 'apodemus', display_name: 'Apex Apodemus', configured_model: 'gemma-4-E2B-Q4_K_M.gguf', provider: 'llama_cpp', sort_order: 6, stability: 'preview', capabilities: ['Local llama.cpp'] }
const weather: LocalCommandStatus = { key: 'weather', command: '/weather', label: 'Weather', description: 'Configured-location forecast.', tool_count: 1, estimated_schema_tokens: 120, available: true, unavailable_reason: null }

function workspaceProps(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}): ComponentProps<typeof CortexWorkspace> {
  return {
    activeAgent: 'panthera', cloudEffort: 'focused', askApexEnabled: true, agentsStatus: [panthera], agentsStatusHydrated: true, history: [], latestTrace: [], error: null, contextUsage: { estimated_prompt_tokens: 45, peak_prompt_tokens: null, context_window: 4096, history_messages_dropped: 0 }, commands: [], armedToolScope: null, onArmedToolScopeChange: vi.fn(), isQuerying: false, lifecycleBusy: false, lifecycleActionPending: false, verifyingCloudAgent: null, onLoadLocalModel: vi.fn().mockResolvedValue(true), onUnloadLocalModel: vi.fn().mockResolvedValue(true), onVerifyCloudAgent: vi.fn().mockResolvedValue(true), snapshotAttached: true, snapshotAvailable: true, onSnapshotAttachedChange: vi.fn(), onAgentChange: vi.fn(), onEffortChange: vi.fn(), onGoogleSearchChange: vi.fn(), onGoogleMapsChange: vi.fn(), onDelphinusXSearchChange: vi.fn(), onOrcinusXSearchChange: vi.fn(), apodemusContextWindow: 8192, onApodemusContextChange: vi.fn(), onSubmit: vi.fn(), onNewSession: vi.fn(), ...overrides,
  }
}

describe('CortexWorkspace', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('uses the available shell width and keeps the conversation before the right inspector', () => {
    render(<CortexWorkspace {...workspaceProps()} />)
    const workspace = screen.getByRole('region', { name: 'Cortex workspace' })
    const inspector = screen.getByLabelText('Cortex inspector')
    expect(workspace.className).not.toContain('max-w-7xl')
    expect(inspector.className).toContain('lg:border-l')
    expect(inspector.previousElementSibling).toHaveTextContent('APEX is ready')
    expect(screen.getByText('Panthera')).not.toHaveAttribute('role', 'button')
  })

  it('offers empty-canvas prompt chips through the active profile submission path', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ onSubmit })} />)

    await user.click(screen.getByRole('button', { name: 'Forecast' }))
    expect(onSubmit).toHaveBeenCalledWith('What is the 5-day weather forecast?', 'panthera')
  })

  it('shows only the selected profile until its anchored selector is opened', async () => {
    const onAgentChange = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ onAgentChange, agentsStatus: [panthera, mus] })} />)
    expect(screen.queryByRole('button', { name: 'Use Apex Neofelis' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Apex Panthera/ }))
    const profileDialog = screen.getByRole('dialog', { name: 'Select agent' })
    expect(profileDialog).toBeInTheDocument()
    expect(profileDialog).toHaveAttribute('id', 'cortex-agent-popover')
    expect(profileDialog.className).toContain('top-full')
    expect(profileDialog.className).toContain('mt-2')
    expect(profileDialog.className).not.toContain('bottom-full')
    await user.click(screen.getByRole('tab', { name: 'Local agents' }))
    expect(onAgentChange).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Use Apex Mus' }))
    expect(onAgentChange).toHaveBeenCalledWith('mus')
  })

  it('keeps Acinonyx first in the development cloud popover and exposes full card names', async () => {
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ activeAgent: 'neofelis', agentsStatus: [acinonyx, panthera, neofelis] })} />)
    await user.click(screen.getByRole('button', { name: /Apex Neofelis/ }))
    const cards = screen.getAllByRole('button', { name: /Use Apex (Acinonyx|Panthera|Neofelis)/ })
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual(['Use Apex Acinonyx', 'Use Apex Panthera', 'Use Apex Neofelis'])
    expect(screen.getAllByText('Powered by Gemini 3.6 Flash')).toHaveLength(2)
  })

  it('uses backend card tags, pricing, effort options, and verification actions', async () => {
    const onEffortChange = vi.fn()
    const onVerifyCloudAgent = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ activeAgent: 'acinonyx', agentsStatus: [acinonyx, panthera], onEffortChange, onVerifyCloudAgent })} />)

    expect(screen.getByRole('combobox', { name: 'Reasoning effort' })).toBeEnabled()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Reasoning effort' }), 'extended')
    expect(onEffortChange).toHaveBeenCalledWith('extended')
    await user.click(screen.getByRole('button', { name: /Apex Acinonyx/ }))
    expect(screen.getByText('Privacy sandbox')).toBeInTheDocument()
    expect(screen.getByText('Masked context')).toBeInTheDocument()
    expect(screen.getByText('Free tier')).toBeInTheDocument()
    expect(screen.getByText(/In \$0\.20\/1M/)).toBeInTheDocument()
    expect(screen.queryByText('Brave Search')).not.toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Verify access' })[0])
    expect(onVerifyCloudAgent).toHaveBeenCalledWith('acinonyx')
  })

  it('keeps agent marks accessible when the catalog changes profile icons', async () => {
    const delphinus: AgentStatus = { ...panthera, key: 'delphinus', display_name: 'Apex Delphinus', provider: 'xai', configured_model: 'grok-4.3', sort_order: 3 }
    const orcinus: AgentStatus = { ...panthera, key: 'orcinus', display_name: 'Apex Orcinus', provider: 'xai', configured_model: 'grok-4.5', sort_order: 4 }
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ agentsStatus: [panthera, delphinus, orcinus] })} />)

    await user.click(screen.getByRole('button', { name: /Apex Panthera/ }))
    expect(screen.getByLabelText('Delphinus agent mark')).toBeInTheDocument()
    expect(screen.getByLabelText('Orcinus agent mark')).toBeInTheDocument()
  })

  it('moves local scopes and context diagnostics into the inspector and arms one next request', async () => {
    const onArmedToolScopeChange = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [mus], commands: [weather], armedToolScope: 'weather', onArmedToolScopeChange })} />)
    expect(screen.getByLabelText('Local tool scopes')).toBeInTheDocument()
    expect(screen.getByText('/weather armed for next request')).toBeInTheDocument()
    expect(screen.getByText('45/4,096')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /\/weather/ }))
    expect(onArmedToolScopeChange).toHaveBeenCalledWith(null)
    expect(screen.queryByText('Commands')).not.toBeInTheDocument()
  })

  it('shows local lifecycle controls only for local profiles and disables them during activity', () => {
    const onLoadLocalModel = vi.fn().mockResolvedValue(true)
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [mus], onLoadLocalModel })} />)
    expect(screen.getByLabelText('Local model lifecycle')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load model' })).toBeEnabled()
    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [mus], lifecycleBusy: true, onLoadLocalModel })} />)
    expect(screen.getByRole('button', { name: 'Load model' })).toBeDisabled()
    rerender(<CortexWorkspace {...workspaceProps()} />)
    expect(screen.queryByLabelText('Local model lifecycle')).not.toBeInTheDocument()
  })

  it('makes every local lifecycle state explicit and only marks transitions as active', () => {
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [mus] })} />)
    expect(screen.getByText('Unloaded')).toBeInTheDocument()
    expect(document.querySelector('.cortex-lifecycle-status--transitioning')).not.toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, active: true }] })} />)
    expect(screen.getByText('Loaded')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, loading: true }] })} />)
    expect(screen.getByText('Loading')).toBeInTheDocument()
    expect(document.querySelector('.cortex-lifecycle-status--transitioning')).toBeInTheDocument()
    expect(document.querySelector('.cortex-lifecycle-spinner')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, status: 'ollama_unreachable', reason: 'Ollama is offline' }] })} />)
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('Ollama is offline')).toBeInTheDocument()
  })

  it('shows the active local model auto-unload countdown in the lifecycle card', () => {
    vi.useFakeTimers()
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, active: true, idle_unload_remaining_seconds: 300 }] })} />)
    expect(screen.getByText('Auto-unload in 05:00')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(screen.getByText('Auto-unload in 04:59')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', lifecycleBusy: true, agentsStatus: [{ ...mus, active: true, idle_unload_remaining_seconds: 299 }] })} />)
    expect(screen.getByText('In use · auto-unload paused')).toBeInTheDocument()
  })

  it('shows Apodemus context selector only when Apodemus is selected', async () => {
    const user = userEvent.setup()
    const onApodemusContextChange = vi.fn()
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'mus',
          agentsStatus: [mus, apodemus],
          onApodemusContextChange,
        })}
      />,
    )
    expect(screen.queryByLabelText('Context window')).not.toBeInTheDocument()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [mus, apodemus],
          apodemusContextWindow: 8192,
          onApodemusContextChange,
        })}
      />,
    )
    const contextSelect = screen.getByLabelText('Context window')
    expect(contextSelect).toBeEnabled()
    expect(contextSelect).toHaveValue('8192')
    await user.selectOptions(contextSelect, '32768')
    expect(onApodemusContextChange).toHaveBeenCalledWith(32768)
  })

  it('disables Apodemus context selector during local generation or loading', () => {
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
        })}
      />,
    )
    expect(screen.getByLabelText('Context window')).toBeEnabled()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [{ ...apodemus, loading: true }],
        })}
      />,
    )
    expect(screen.getByLabelText('Context window')).toBeDisabled()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
          lifecycleBusy: true,
        })}
      />,
    )
    expect(screen.getByLabelText('Context window')).toBeDisabled()
  })
})
