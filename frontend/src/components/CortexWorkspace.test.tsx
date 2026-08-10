import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps, ReactElement } from 'react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CortexWorkspace } from './CortexWorkspace'
import type { AgentStatus, ToolCatalog, ToolPreflightEstimate } from '../types/telemetry'
import type { ApexLogoProps } from './ApexLogo'

const panthera: AgentStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.', configured_model: 'gpt-5.6-luna', sort_order: 1, capabilities: ['Generalist', 'Planning'], native_tools: {}, provider: 'openai', version: '7.4', runtime: 'cloud', tier: 'balanced', stability: 'stable', effort_options: ['light', 'focused', 'extended'], default_effort: 'focused', context_window: null, context_window_options: null, context_window_high_resource_options: null, default_context_window: null, reasoning_mode: null, reasoning_mode_options: null, default_reasoning_mode: null, status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: 0.02, long_context_threshold_tokens: 272000, long_context_input_per_million: 0.4, long_context_output_per_million: 1.8, long_context_cached_input_per_million: 0.04 }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}
const neofelis: AgentStatus = { ...panthera, key: 'neofelis', display_name: 'Apex Neofelis', configured_model: 'gemini-3.6-flash', provider: 'gemini', sort_order: 2, capabilities: ['Research', 'Google Search', 'Google Maps'], native_tools: { google_search: true, google_maps: true } }
const acinonyx: AgentStatus = { ...neofelis, key: 'acinonyx', display_name: 'Apex Acinonyx', configured_model: 'gemini-3.5-flash-lite', sort_order: 0, capabilities: ['Privacy sandbox', 'Masked context'], pricing: { ...neofelis.pricing, billing_basis: 'free_tier', input_per_million: 0, output_per_million: 0 } }
const mus: AgentStatus = { ...panthera, key: 'mus', display_name: 'Apex Mus', configured_model: 'qwen3:4b-instruct', provider: 'ollama', runtime: 'local', sort_order: 5, capabilities: ['Larger model', 'Primary local'], effort_options: null, default_effort: null, reasoning_mode: 'none', reasoning_mode_options: ['none'], default_reasoning_mode: 'none', status: 'available', status_source: 'runtime', active: false, pricing: { ...panthera.pricing, billing_basis: 'local', input_per_million: 0, output_per_million: 0 } }
const apodemus: AgentStatus = { ...mus, key: 'apodemus', display_name: 'Apex Apodemus', configured_model: 'gemma-4-E2B-Q4_K_M.gguf', provider: 'llama_cpp', sort_order: 6, stability: 'stable', capabilities: ['Local llama.cpp'], context_window: 16384, context_window_options: [4096, 16384, 32768, 131072], context_window_high_resource_options: [131072], default_context_window: 16384, reasoning_mode: 'none', reasoning_mode_options: ['none', 'focused'], default_reasoning_mode: 'none' }
const neotoma: AgentStatus = { ...apodemus, key: 'neotoma', display_name: 'Apex Neotoma', configured_model: 'gemma-4-E4B-Q4_K_M.gguf', sort_order: 7, context_window: 16384, context_window_options: [4096, 16384, 32768, 65536], context_window_high_resource_options: [65536], default_context_window: 16384 }
const toolCatalog: ToolCatalog = {
  agent: 'panthera',
  groups: [{
    id: 'family:schedule',
    label: 'Schedule',
    kind: 'apex_family',
    tool_count: 2,
    schema_token_subtotal: 160,
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
        estimated_schema_tokens: 80,
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
        estimated_schema_tokens: 80,
        allowed_for_agent: true,
      },
    ],
  }],
  tools: [{
    name: 'get_upcoming_calendar_events',
    label: 'Calendar events',
    description: 'Calendar',
    origin: 'native',
    source_id: 'apex',
    apex_family: 'schedule',
    risk: 'read',
    available: true,
    unavailable_reason: null,
    estimated_schema_tokens: 80,
    allowed_for_agent: true,
  }, {
    name: 'get_active_reminders',
    label: 'Reminders',
    description: 'Reminders',
    origin: 'native',
    source_id: 'apex',
    apex_family: 'schedule',
    risk: 'read',
    available: true,
    unavailable_reason: null,
    estimated_schema_tokens: 80,
    allowed_for_agent: true,
  }],
  profiles: [],
  default_profile_id: 'no_tools',
  default_profile_name: 'No APEX Tools',
  default_selected_tool_names: [],
  provider_hosted_tools: [],
  context_window: 4096,
  reserved_response_tokens: 512,
}

function workspaceProps(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}): ComponentProps<typeof CortexWorkspace> {
  return {
    activeAgent: 'panthera', cloudEffort: 'focused', askApexEnabled: true, agentsStatus: [panthera], agentsStatusHydrated: true, history: [], latestTrace: [], error: null, contextUsage: { estimated_prompt_tokens: 45, peak_prompt_tokens: null, context_window: 4096, history_messages_dropped: 0 }, toolCatalog, selectedToolNames: [], activeToolProfileId: null, selectionReady: true, onToolSelectionChange: vi.fn(), onToolProfileChange: vi.fn(), isQuerying: false, logoProps: { step: null, status: 'idle' } satisfies Omit<ApexLogoProps, 'className'>, lifecycleBusy: false, lifecycleActionPending: false, verifyingCloudAgent: null, onLoadLocalModel: vi.fn().mockResolvedValue(true), onUnloadLocalModel: vi.fn().mockResolvedValue(true), onVerifyCloudAgent: vi.fn().mockResolvedValue(true), snapshotAttached: true, snapshotAvailable: true, onSnapshotAttachedChange: vi.fn(), onAgentChange: vi.fn(), onEffortChange: vi.fn(), onGoogleSearchChange: vi.fn(), onGoogleMapsChange: vi.fn(), onDelphinusXSearchChange: vi.fn(), onOrcinusXSearchChange: vi.fn(), onLocalContextWindowChange: vi.fn(), onLocalReasoningModeChange: vi.fn(), onSubmit: vi.fn().mockResolvedValue(true), onNewSession: vi.fn(), ...overrides,
  }
}

describe('CortexWorkspace', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the shared live logo in the header', () => {
    const { container } = render(
      <CortexWorkspace
        {...workspaceProps({
          logoProps: {
            step: 3,
            status: 'loading',
            outerShellActivity: 'synthesis',
          },
        })}
      />,
    )

    const logo = container.querySelector('[data-slot="cortex-logo"]')
    expect(logo).toBeInTheDocument()
    expect(logo?.querySelector('#blue-crown-top')).toHaveClass('apex-blue-metal--active')
  })

  it('offers empty-canvas prompt chips through the active profile submission path', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ onSubmit })} />)

    await user.click(screen.getByRole('button', { name: 'Forecast' }))
    expect(onSubmit).toHaveBeenCalledWith('What is the 5-day weather forecast?', 'panthera', [], null)
  })

  it('hides prompt chips when preflight reports a strict selection failure', () => {
    render(
      <CortexWorkspace
        {...workspaceProps({
          toolPreflight: { can_proceed: false } as ToolPreflightEstimate,
        })}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Forecast' })).not.toBeInTheDocument()
  })

  it('submits the footer with the chosen tool set on every request', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    function Harness(): ReactElement {
      const [selected, setSelected] = useState<string[]>([])
      return <CortexWorkspace {...workspaceProps({
        onSubmit,
        selectedToolNames: selected,
        onToolSelectionChange: setSelected,
      })} />
    }

    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /Tools:/ }))
    await user.click(screen.getByRole('checkbox', { name: 'Select Schedule' }))
    await user.click(screen.getByRole('button', { name: 'Expand Schedule' }))
    await user.click(screen.getByRole('checkbox', { name: /Reminders/ }))

    const input = screen.getByLabelText('Ask APEX query')
    await user.type(input, 'First request')
    await user.click(screen.getByRole('button', { name: 'Send query' }))
    await user.type(input, 'Second request')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onSubmit).toHaveBeenNthCalledWith(
      1,
      'First request',
      'panthera',
      ['get_upcoming_calendar_events'],
      null,
    )
    expect(onSubmit).toHaveBeenNthCalledWith(
      2,
      'Second request',
      'panthera',
      ['get_upcoming_calendar_events'],
      null,
    )
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

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, active: true }] })} />)
    expect(screen.getByText('Loaded')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'mus', agentsStatus: [{ ...mus, loading: true }] })} />)
    expect(screen.getByText('Loading')).toBeInTheDocument()

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

  it('shows a context selector only when the selected local Agent advertises one', async () => {
    const user = userEvent.setup()
    const onLocalContextWindowChange = vi.fn()
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'mus',
          agentsStatus: [mus, apodemus, neotoma],
          onLocalContextWindowChange,
        })}
      />,
    )
    expect(screen.queryByLabelText('Context window')).not.toBeInTheDocument()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [mus, apodemus, neotoma],
          onLocalContextWindowChange,
        })}
      />,
    )
    const contextSelect = screen.getByLabelText('Context window')
    expect(contextSelect).toBeEnabled()
    expect(contextSelect).toHaveValue('16384')
    expect(screen.getByRole('option', { name: '132K High resource' })).toBeInTheDocument()
    await user.selectOptions(contextSelect, '32768')
    expect(onLocalContextWindowChange).toHaveBeenCalledWith('apodemus', 32768)
    expect(screen.queryByText('32K High resource')).not.toBeInTheDocument()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'neotoma',
          agentsStatus: [mus, apodemus, neotoma],
          onLocalContextWindowChange,
        })}
      />,
    )
    const neotomaContextSelect = screen.getByLabelText('Context window')
    expect(neotomaContextSelect).toHaveValue('16384')
    expect(screen.getByRole('option', { name: '64K High resource' })).toBeInTheDocument()
    await user.selectOptions(neotomaContextSelect, '65536')
    expect(onLocalContextWindowChange).toHaveBeenCalledWith('neotoma', 65536)
  })

  it('shows a local reasoning selector only when an Agent supports multiple modes', async () => {
    const user = userEvent.setup()
    const onLocalReasoningModeChange = vi.fn()
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'mus',
          agentsStatus: [mus, apodemus],
          onLocalReasoningModeChange,
        })}
      />,
    )
    expect(screen.queryByLabelText('Reasoning')).not.toBeInTheDocument()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [mus, apodemus],
          onLocalReasoningModeChange,
        })}
      />,
    )
    const reasoningSelect = screen.getByLabelText('Reasoning')
    expect(reasoningSelect).toBeEnabled()
    expect(reasoningSelect).toHaveValue('none')
    await user.selectOptions(reasoningSelect, 'focused')
    expect(onLocalReasoningModeChange).toHaveBeenCalledWith('apodemus', 'focused')
  })

  it('optimistically updates local selectors and rolls back context and reasoning on persistence failure', async () => {
    const user = userEvent.setup()
    let rejectContext!: (persisted: boolean) => void
    let rejectReasoning!: (persisted: boolean) => void
    const contextPersistence = new Promise<boolean>((resolve) => {
      rejectContext = resolve
    })
    const reasoningPersistence = new Promise<boolean>((resolve) => {
      rejectReasoning = resolve
    })
    const onLocalContextWindowChange = vi.fn().mockReturnValue(contextPersistence)
    const onLocalReasoningModeChange = vi.fn().mockReturnValue(reasoningPersistence)
    render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
          onLocalContextWindowChange,
          onLocalReasoningModeChange,
        })}
      />,
    )

    const contextSelect = screen.getByLabelText('Context window')
    const reasoningSelect = screen.getByLabelText('Reasoning')
    await user.selectOptions(contextSelect, '32768')
    await user.selectOptions(reasoningSelect, 'focused')
    expect(contextSelect).toHaveValue('32768')
    expect(reasoningSelect).toHaveValue('focused')

    rejectContext(false)
    rejectReasoning(false)
    await waitFor(() => {
      expect(contextSelect).toHaveValue('16384')
      expect(reasoningSelect).toHaveValue('none')
    })
  })

  it('reconciles optimistic local selections with refreshed authoritative Agent status', async () => {
    const user = userEvent.setup()
    let resolveContext!: (persisted: boolean) => void
    const contextPersistence = new Promise<boolean>((resolve) => {
      resolveContext = resolve
    })
    const onLocalContextWindowChange = vi.fn().mockReturnValue(contextPersistence)
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
          onLocalContextWindowChange,
        })}
      />,
    )

    const contextSelect = screen.getByLabelText('Context window')
    await user.selectOptions(contextSelect, '32768')
    expect(contextSelect).toHaveValue('32768')
    resolveContext(true)
    expect(contextSelect).toHaveValue('32768')
    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [{ ...apodemus, context_window: 32768 }],
          onLocalContextWindowChange,
        })}
      />,
    )
    await waitFor(() => expect(contextSelect).toHaveValue('32768'))
  })

  it('keeps the optimistic context selection after persistence succeeds until authority catches up', async () => {
    const user = userEvent.setup()
    let resolveContext!: (persisted: boolean) => void
    const contextPersistence = new Promise<boolean>((resolve) => {
      resolveContext = resolve
    })
    const onLocalContextWindowChange = vi.fn().mockReturnValue(contextPersistence)
    const { rerender } = render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
          onLocalContextWindowChange,
        })}
      />,
    )

    const contextSelect = screen.getByLabelText('Context window')
    await user.selectOptions(contextSelect, '32768')
    expect(contextSelect).toBeDisabled()
    resolveContext(true)
    await waitFor(() => expect(contextSelect).toBeEnabled())
    expect(contextSelect).toHaveValue('32768')

    // Stale authority must not snap the selector back, and the control must
    // remain usable for another change even before refreshed status catches up.
    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'apodemus',
          agentsStatus: [apodemus],
          onLocalContextWindowChange,
        })}
      />,
    )
    expect(contextSelect).toHaveValue('32768')
    expect(contextSelect).toBeEnabled()
    onLocalContextWindowChange.mockResolvedValue(true)
    await user.selectOptions(contextSelect, '4096')
    await waitFor(() => expect(contextSelect).toHaveValue('4096'))
  })

  it('disables local context selection during generation or loading', () => {
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

  it('renders agent response markdown elements including headings, bold text, links, code, and tables', () => {
    const markdownContent = [
      '# Cortex Response Header',
      'This contains **bold text**, `inline code`, and a [Documentation Link](https://apex.example/docs).',
      '| Feature | Status |\n| --- | --- |\n| Markdown | Supported |',
    ].join('\n\n')

    render(
      <CortexWorkspace
        {...workspaceProps({
          history: [
            {
              role: 'agent',
              content: markdownContent,
            },
          ],
        })}
      />,
    )

    expect(screen.getByRole('heading', { level: 1, name: 'Cortex Response Header' })).toBeInTheDocument()
    expect(screen.getByText('bold text')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Documentation Link' })
    expect(link).toHaveAttribute('href', 'https://apex.example/docs')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Supported')).toBeInTheDocument()
  })

  it('keeps Google Maps sources beside the response and isolates Search Suggestions markup', () => {
    render(
      <CortexWorkspace
        {...workspaceProps({
          history: [{
            role: 'agent',
            content: 'A grounded answer with [Google Maps: Cafe](https://maps.google.com/cafe).',
            metadata: {
              agent: null,
              usage: null,
              timing: null,
              cost: null,
              citations: [{ title: 'Cafe', uri: 'https://maps.google.com/cafe', snippet: null, source: 'google_maps' }],
              grounding: { searchSuggestionsHtml: '<a href="https://www.google.com/search">Search</a>' },
              toolSelection: null,
            },
          }],
        })}
      />,
    )

    expect(screen.getByRole('region', { name: 'Google Maps sources' })).toHaveTextContent('Google Maps: Cafe')
    const suggestions = screen.getByTitle('Google Search suggestions')
    expect(suggestions).toHaveAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox')
    expect(suggestions).toHaveAttribute('srcdoc', '<a href="https://www.google.com/search">Search</a>')
  })

  it('uses display labels rather than raw cloud provider IDs in response metadata', () => {
    render(
      <CortexWorkspace
        {...workspaceProps({
          history: [{
            role: 'agent',
            content: 'Research complete.',
            metadata: {
              agent: {
                key: 'orcinus', version: '1.0', provider: 'xai', configuredModel: 'grok-4.5', resolvedModel: 'grok-4.5', requestedEffort: 'extended', resolvedEffort: 'high',
              },
              usage: null, timing: null, cost: null, citations: [], grounding: null, toolSelection: null,
            },
          }],
        })}
      />,
    )

    expect(screen.getByText('SpaceXAI / orcinus')).toBeInTheDocument()
    expect(screen.queryByText('xai / orcinus')).not.toBeInTheDocument()
  })
})
