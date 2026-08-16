import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps, ReactElement } from 'react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CortexWorkspace } from './CortexWorkspace'
import type { AgentStatus, ToolCatalog, ToolPreflightEstimate } from '../types/telemetry'
import type { ApexLogoProps } from './ApexLogo'

const panthera: AgentStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.', configured_model: 'gpt-5.6-luna', sort_order: 1, capabilities: ['Generalist', 'Planning'], native_tools: {}, provider: 'openai', version: '2.0', runtime: 'cloud', tier: 'balanced', stability: 'stable', model_stability: 'stable', effort_options: ['light', 'focused', 'extended'], default_effort: 'focused', context_window: null, context_window_options: null, context_window_high_resource_options: null, default_context_window: null, reasoning_mode: null, reasoning_mode_options: null, default_reasoning_mode: null, status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: 0.02, long_context_threshold_tokens: 272000, long_context_input_per_million: 0.4, long_context_output_per_million: 1.8, long_context_cached_input_per_million: 0.04 }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}
const lynx: AgentStatus = { ...panthera, key: 'lynx', display_name: 'Apex Lynx', configured_model: 'gemma-4-E2B-Q4_K_M.gguf', provider: 'llama_cpp', runtime: 'local', sort_order: 2, capabilities: ['Local', 'Private'], effort_options: null, default_effort: null, status: 'available', status_source: 'runtime', context_window: 16384, context_window_options: [4096, 16384, 32768, 131072], context_window_high_resource_options: [131072], default_context_window: 16384, reasoning_mode: 'none', reasoning_mode_options: ['none', 'focused'], default_reasoning_mode: 'none', pricing: { ...panthera.pricing, billing_basis: 'local', input_per_million: 0, output_per_million: 0 } }
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
    activeAgent: 'panthera',
    cloudEffort: 'focused',
    pantheraModel: 'gpt-5.6-luna',
    lynxModel: 'gemma-4-E2B-Q4_K_M.gguf',
    pantheraHostedTools: { google_search: true, google_maps: true, x_search: true },
    devModeActive: false,
    sandboxMode: false,
    agentQueriesEnabled: true,
    agentsStatus: [panthera, lynx],
    agentsStatusHydrated: true,
    history: [],
    latestTrace: [],
    error: null,
    contextUsage: { estimated_prompt_tokens: 45, peak_prompt_tokens: null, context_window: 4096, history_messages_dropped: 0 },
    toolCatalog,
    selectedToolNames: [],
    activeToolProfileId: null,
    selectionReady: true,
    onToolSelectionChange: vi.fn(),
    onToolProfileChange: vi.fn(),
    isQuerying: false,
    logoProps: { step: null, status: 'idle' } satisfies Omit<ApexLogoProps, 'className'>,
    lifecycleBusy: false,
    lifecycleActionPending: false,
    verifyingCloudAgent: null,
    onLoadLocalModel: vi.fn().mockResolvedValue(true),
    onUnloadLocalModel: vi.fn().mockResolvedValue(true),
    onVerifyCloudAgent: vi.fn().mockResolvedValue(true),
    snapshotAttached: true,
    snapshotAvailable: true,
    onSnapshotAttachedChange: vi.fn(),
    onAgentChange: vi.fn(),
    onPantheraModelChange: vi.fn(),
    onLynxModelChange: vi.fn(),
    onEffortChange: vi.fn(),
    onHostedToolChange: vi.fn(),
    onSandboxModeChange: vi.fn(),
    onLocalContextWindowChange: vi.fn().mockResolvedValue(true),
    onLocalReasoningModeChange: vi.fn().mockResolvedValue(true),
    onSubmit: vi.fn().mockResolvedValue(true),
    onNewSession: vi.fn(),
    actions: { actions: [], pendingCount: 0, isLoading: false, error: null, selectedActionId: null, detail: null, isDetailLoading: false, mutation: null, setSelectedActionId: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), resolve: vi.fn().mockResolvedValue(undefined) },
    demoModeActive: false,
    ...overrides,
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
    const mark = logo?.firstElementChild
    expect(mark).toHaveAttribute('aria-hidden', 'true')
    expect(mark).toHaveClass('h-8', 'w-auto')
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

    const input = screen.getByLabelText('Agent query')
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

  it('switches active agent directly via the segmented agent cards', async () => {
    const onAgentChange = vi.fn()
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ onAgentChange, agentsStatus: [panthera, lynx] })} />)
    const lynxRadio = screen.getByRole('radio', { name: /Lynx, Local · Private/i })
    expect(lynxRadio).toBeInTheDocument()
    await user.click(lynxRadio)
    expect(onAgentChange).toHaveBeenCalledWith('lynx')
  })

  it('uses backend pricing, effort options, and verification actions on the model selector', async () => {
    const onEffortChange = vi.fn()
    const onVerifyCloudAgent = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<CortexWorkspace {...workspaceProps({ activeAgent: 'panthera', agentsStatus: [panthera, lynx], onEffortChange, onVerifyCloudAgent })} />)

    expect(screen.getByRole('combobox', { name: 'Reasoning effort' })).toBeEnabled()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Reasoning effort' }), 'extended')
    expect(onEffortChange).toHaveBeenCalledWith('extended')
    expect(screen.getByText('$0.20/M in · $1.20/M out')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(onVerifyCloudAgent).toHaveBeenCalledWith('panthera')
  })

  it('exposes model selection with rich model browser popover', async () => {
    const user = userEvent.setup()
    const onPantheraModelChange = vi.fn()
    const { rerender } = render(
      <CortexWorkspace {...workspaceProps({ activeAgent: 'panthera', onPantheraModelChange })} />,
    )

    const modelRegion = screen.getByRole('region', { name: 'Model selection' })
    expect(modelRegion).toBeInTheDocument()
    expect(within(modelRegion).getByText('gpt-5.6-luna')).toBeInTheDocument()
    await user.click(within(modelRegion).getByRole('button', { expanded: false }))
    expect(screen.getByRole('listbox', { name: 'Select model for panthera' })).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [lynx] })} />)
    const lynxModelRegion = screen.getByRole('region', { name: 'Model selection' })
    expect(within(lynxModelRegion).getAllByText('gemma-4-E2B-Q4_K_M.gguf').length).toBeGreaterThanOrEqual(1)
    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'panthera' })} />)
  })

  it('keeps agent marks accessible for Panthera and Lynx', () => {
    render(<CortexWorkspace {...workspaceProps({ agentsStatus: [panthera, lynx] })} />)

    expect(screen.getAllByLabelText('Panthera agent mark').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByLabelText('Lynx agent mark').length).toBeGreaterThanOrEqual(1)
  })

  it('shows local lifecycle controls only for local profiles and disables them during activity', () => {
    const onLoadLocalModel = vi.fn().mockResolvedValue(true)
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [lynx], onLoadLocalModel })} />)
    expect(screen.getByLabelText('Local model lifecycle')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load model' })).toBeEnabled()
    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [lynx], lifecycleBusy: true, onLoadLocalModel })} />)
    expect(screen.getByRole('button', { name: 'Load model' })).toBeDisabled()
    rerender(<CortexWorkspace {...workspaceProps()} />)
    expect(screen.queryByLabelText('Local model lifecycle')).not.toBeInTheDocument()
  })

  it('makes every local lifecycle state explicit and only marks transitions as active', () => {
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [lynx] })} />)
    const lifecycleRegion = screen.getByLabelText('Local model lifecycle')
    expect(within(lifecycleRegion).getByText('Unloaded')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [{ ...lynx, active: true }] })} />)
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Loaded')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [{ ...lynx, loading: true }] })} />)
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Loading…')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [{ ...lynx, status: 'ollama_unreachable', reason: 'Ollama is offline' }] })} />)
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('Ollama is offline')).toBeInTheDocument()
  })

  it('shows the active local model auto-unload countdown in the lifecycle card', () => {
    vi.useFakeTimers()
    const { rerender } = render(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', agentsStatus: [{ ...lynx, active: true, idle_unload_remaining_seconds: 300 }] })} />)
    expect(screen.getByText('Auto-unload in 05:00')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(screen.getByText('Auto-unload in 04:59')).toBeInTheDocument()

    rerender(<CortexWorkspace {...workspaceProps({ activeAgent: 'lynx', lifecycleBusy: true, agentsStatus: [{ ...lynx, active: true, idle_unload_remaining_seconds: 299 }] })} />)
    expect(screen.getByText('In use · auto-unload paused')).toBeInTheDocument()
  })

  it('shows context and reasoning selectors for Lynx', async () => {
    const user = userEvent.setup()
    const onLocalContextWindowChange = vi.fn().mockResolvedValue(true)
    const onLocalReasoningModeChange = vi.fn().mockResolvedValue(true)
    render(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'lynx',
          agentsStatus: [lynx],
          onLocalContextWindowChange,
          onLocalReasoningModeChange,
        })}
      />,
    )

    const contextSelect = screen.getByLabelText('Context window')
    expect(contextSelect).toBeEnabled()
    expect(contextSelect).toHaveValue('16384')
    expect(screen.getByRole('option', { name: '132K High resource' })).toBeInTheDocument()
    await user.selectOptions(contextSelect, '32768')
    expect(onLocalContextWindowChange).toHaveBeenCalledWith(32768)

    const reasoningSelect = screen.getByLabelText('Reasoning')
    expect(reasoningSelect).toHaveValue('none')
    await user.selectOptions(reasoningSelect, 'focused')
    expect(onLocalReasoningModeChange).toHaveBeenCalledWith('focused')
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
          activeAgent: 'lynx',
          agentsStatus: [lynx],
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
          activeAgent: 'lynx',
          agentsStatus: [lynx],
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
          activeAgent: 'lynx',
          agentsStatus: [{ ...lynx, context_window: 32768 }],
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
          activeAgent: 'lynx',
          agentsStatus: [lynx],
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
          activeAgent: 'lynx',
          agentsStatus: [lynx],
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
          activeAgent: 'lynx',
          agentsStatus: [lynx],
        })}
      />,
    )
    expect(screen.getByLabelText('Context window')).toBeEnabled()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'lynx',
          agentsStatus: [{ ...lynx, loading: true }],
        })}
      />,
    )
    expect(screen.getByLabelText('Context window')).toBeDisabled()

    rerender(
      <CortexWorkspace
        {...workspaceProps({
          activeAgent: 'lynx',
          agentsStatus: [lynx],
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
                key: 'panthera', version: '1.0', provider: 'xai', configuredModel: 'grok-4.5', resolvedModel: 'grok-4.5', requestedEffort: 'extended', resolvedEffort: 'high',
              },
              usage: null, timing: null, cost: null, citations: [], grounding: null, toolSelection: null,
            },
          }],
        })}
      />,
    )

    expect(screen.getByText('SpaceXAI / panthera')).toBeInTheDocument()
    expect(screen.queryByText('xai / panthera')).not.toBeInTheDocument()
  })
})
