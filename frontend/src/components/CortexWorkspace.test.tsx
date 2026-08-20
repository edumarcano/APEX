import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AssistantResponseDisplay, CortexWorkspace, ResponseMetrics } from './CortexWorkspace'
import { ApexAssistantRuntime } from './ApexAssistantRuntime'
import type { AgentQueryMetadata } from '../lib/cortexResponse'
import type { AgentStatus, CloudEffort, ToolCatalog } from '../types/telemetry'
import type { ApexLogoProps } from './ApexLogo'

const pantheraModelCatalog = [
  {
    model_id: 'gpt-5.6-luna',
    display_name: 'GPT-5.6 Luna',
    provider: 'openai' as const,
    runtime: 'cloud' as const,
    stability: 'stable' as const,
    hosted_capabilities: [],
    pricing: {
      currency: 'USD' as const,
      pricing_version: '2026.08.02',
      billing_basis: 'standard' as const,
      input_per_million: 0.2,
      output_per_million: 1.2,
      cached_input_per_million: 0.02,
      long_context_threshold_tokens: 272000,
      long_context_input_per_million: 0.4,
      long_context_output_per_million: 1.8,
      long_context_cached_input_per_million: 0.04,
    },
    reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'] as CloudEffort[],
    default_reasoning: 'medium' as CloudEffort,
  },
]

const felisModelCatalog = [
  {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp' as const,
    runtime: 'local' as const,
    stability: 'stable' as const,
    hosted_capabilities: [],
    pricing: {
      currency: 'USD' as const,
      pricing_version: '2026.08.02',
      billing_basis: 'local' as const,
      input_per_million: 0,
      output_per_million: 0,
      cached_input_per_million: 0,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
  },
]

const panthera: AgentStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.', configured_model: 'gpt-5.6-luna', sort_order: 1, capabilities: ['Generalist', 'Planning'], native_tools: {}, provider: 'openai', runtime: 'cloud', model_stability: 'stable', reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'], default_reasoning: 'medium', context_window: null, context_window_options: null, context_window_high_resource_options: null, default_context_window: null, reasoning_mode: null, reasoning_mode_options: null, default_reasoning_mode: null, status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: 0.02, long_context_threshold_tokens: 272000, long_context_input_per_million: 0.4, long_context_output_per_million: 1.8, long_context_cached_input_per_million: 0.04 }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null, model_catalog: pantheraModelCatalog,
}
const felis: AgentStatus = { ...panthera, key: 'felis', display_name: 'Apex Felis', configured_model: 'gemma-4-E2B-Q4_K_M.gguf', provider: 'llama_cpp', runtime: 'local', sort_order: 2, capabilities: ['Local', 'Private'], reasoning_options: null, default_reasoning: null, status: 'available', status_source: 'runtime', context_window: 16384, context_window_options: [4096, 16384, 32768, 131072], context_window_high_resource_options: [131072], default_context_window: 16384, reasoning_mode: 'none', reasoning_mode_options: ['none', 'focused'], default_reasoning_mode: 'none', pricing: { ...panthera.pricing, billing_basis: 'local', input_per_million: 0, output_per_million: 0 }, model_catalog: felisModelCatalog }
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
    cloudEffort: 'medium',
    pantheraModel: 'gpt-5.6-luna',
    felisModel: 'gemma-4-E2B-Q4_K_M.gguf',
    pantheraHostedTools: { google_search: true, google_maps: true, x_search: true },
    devModeActive: false,
    sandboxMode: false,
    agentQueriesEnabled: true,
    agentsStatus: [panthera, felis],
    agentsStatusHydrated: true,
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
    onFelisModelChange: vi.fn(),
    onEffortChange: vi.fn(),
    onHostedToolChange: vi.fn(),
    onSandboxModeChange: vi.fn(),
    onLocalContextWindowChange: vi.fn().mockResolvedValue(true),
    onLocalReasoningModeChange: vi.fn().mockResolvedValue(true),
    actions: { actions: [], pendingCount: 0, isLoading: false, error: null, selectedActionId: null, detail: null, isDetailLoading: false, mutation: null, setSelectedActionId: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), resolve: vi.fn().mockResolvedValue(undefined) },
    demoModeActive: false,
    assistantRunConfig: { agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null },
    ...overrides,
  }
}

function renderWorkspace(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}): ReturnType<typeof render> {
  const props = workspaceProps(overrides)
  return render(
    <ApexAssistantRuntime config={props.assistantRunConfig}>
      <CortexWorkspace {...props} />
    </ApexAssistantRuntime>,
  )
}

describe('CortexWorkspace', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/v1/cortex/conversations')) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(null, { status: 200 })
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('collapses response information until it is explicitly expanded', async () => {
    const metadata: AgentQueryMetadata = {
      agent: { key: 'panthera', version: null, provider: 'gemini', configuredModel: 'gemini-2.5-pro', resolvedModel: 'gemini-2.5-pro', requestedEffort: null, resolvedEffort: null },
      usage: { inputTokens: 120, cachedInputTokens: null, reasoningTokens: null, outputTokens: 30, totalTokens: 150 },
      timing: { totalMs: 820, providerMs: 700, apexToolMs: 40 },
      cost: { tokenCost: 0.01, hostedToolCost: 0, totalCost: 0.01, currency: 'USD', pricingVersion: 'v1', completeness: 'complete' },
      citations: [],
      grounding: null,
      toolSelection: null,
    }
    const user = userEvent.setup()

    render(<ResponseMetrics metadata={metadata} />)

    const disclosure = screen.getByText('Response information')
    expect(disclosure).toBeVisible()
    expect(screen.queryByText('Latency')).not.toBeVisible()

    await user.click(disclosure)
    expect(screen.getByText('Latency')).toBeVisible()
    expect(screen.getByText('820 ms')).toBeVisible()
  })

  it('renders the brain circuit icon badge in the header and the shared live logo in the chat canvas', () => {
    const { container } = renderWorkspace({
      logoProps: {
        step: 3,
        status: 'loading',
        outerShellActivity: 'synthesis',
      },
    })

    const header = container.querySelector('header')
    expect(header?.querySelector('.hud-icon-badge')).toBeInTheDocument()
    expect(header?.querySelector('[data-slot="cortex-logo"]')).toBeNull()

    const chatLogo = container.querySelector('[data-slot="cortex-chat-logo"]')
    expect(chatLogo).toBeInTheDocument()
    const mark = chatLogo?.firstElementChild
    expect(mark).toHaveAttribute('aria-hidden', 'true')
    expect(chatLogo?.querySelector('#blue-crown-top')).toHaveClass('apex-blue-metal--active')
  })

  it('switches active agent directly via the segmented agent cards', async () => {
    const onAgentChange = vi.fn()
    const user = userEvent.setup()
    renderWorkspace({ onAgentChange, agentsStatus: [panthera, felis] })
    const felisRadio = screen.getByRole('radio', { name: /Apex Felis.*Local · Private/i })
    expect(felisRadio).toBeInTheDocument()
    await user.click(felisRadio)
    expect(onAgentChange).toHaveBeenCalledWith('felis')
  })

  it('uses backend pricing, effort options, and verification actions on the model selector', async () => {
    const onEffortChange = vi.fn()
    const onVerifyCloudAgent = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderWorkspace({ activeAgent: 'panthera', agentsStatus: [panthera, felis], onEffortChange, onVerifyCloudAgent })

    expect(screen.getByRole('combobox', { name: 'Reasoning effort' })).toBeEnabled()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Reasoning effort' }), 'xhigh')
    expect(onEffortChange).toHaveBeenCalledWith('xhigh')
    expect(screen.getByText('$0.20/M in · $1.20/M out')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(onVerifyCloudAgent).toHaveBeenCalledWith('panthera')
  })

  it('exposes model selection with rich model browser popover', async () => {
    const user = userEvent.setup()
    const onPantheraModelChange = vi.fn()
    const { rerender } = renderWorkspace({ activeAgent: 'panthera', onPantheraModelChange })

    const modelRegion = screen.getByRole('region', { name: 'Model selection' })
    expect(modelRegion).toBeInTheDocument()
    expect(within(modelRegion).getByText('GPT-5.6 Luna')).toBeInTheDocument()
    await user.click(within(modelRegion).getByRole('button', { expanded: false }))
    expect(screen.getByRole('listbox', { name: 'Select model for panthera' })).toBeInTheDocument()

    const felisProps = workspaceProps({ activeAgent: 'felis', agentsStatus: [felis] })
    rerender(
      <ApexAssistantRuntime config={felisProps.assistantRunConfig}>
        <CortexWorkspace {...felisProps} />
      </ApexAssistantRuntime>,
    )
    const felisModelRegion = screen.getByRole('region', { name: 'Model selection' })
    expect(within(felisModelRegion).getAllByText('Gemma 4 E2B').length).toBeGreaterThanOrEqual(1)
  })

  it('keeps agent marks accessible for Panthera and Felis', () => {
    renderWorkspace({ agentsStatus: [panthera, felis] })

    expect(screen.getAllByLabelText('Panthera agent mark').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByLabelText('Felis agent mark').length).toBeGreaterThanOrEqual(1)
  })

  it('shows local lifecycle controls only for local profiles and disables them during activity', () => {
    const onLoadLocalModel = vi.fn().mockResolvedValue(true)
    const { rerender } = renderWorkspace({ activeAgent: 'felis', agentsStatus: [felis], onLoadLocalModel })
    expect(screen.getByLabelText('Local model lifecycle')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load model' })).toBeEnabled()

    const busyProps = workspaceProps({ activeAgent: 'felis', agentsStatus: [felis], lifecycleBusy: true, onLoadLocalModel })
    rerender(
      <ApexAssistantRuntime config={busyProps.assistantRunConfig}>
        <CortexWorkspace {...busyProps} />
      </ApexAssistantRuntime>,
    )
    expect(screen.getByRole('button', { name: 'Load model' })).toBeDisabled()

    const defaultProps = workspaceProps()
    rerender(
      <ApexAssistantRuntime config={defaultProps.assistantRunConfig}>
        <CortexWorkspace {...defaultProps} />
      </ApexAssistantRuntime>,
    )
    expect(screen.queryByLabelText('Local model lifecycle')).not.toBeInTheDocument()
  })

  it('makes every local lifecycle state explicit and only marks transitions as active', () => {
    const { rerender } = renderWorkspace({ activeAgent: 'felis', agentsStatus: [felis] })
    const lifecycleRegion = screen.getByLabelText('Local model lifecycle')
    expect(within(lifecycleRegion).getByText('Unloaded')).toBeInTheDocument()

    const loadedProps = workspaceProps({ activeAgent: 'felis', agentsStatus: [{ ...felis, active: true }] })
    rerender(
      <ApexAssistantRuntime config={loadedProps.assistantRunConfig}>
        <CortexWorkspace {...loadedProps} />
      </ApexAssistantRuntime>,
    )
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Loaded')).toBeInTheDocument()

    const loadingProps = workspaceProps({ activeAgent: 'felis', agentsStatus: [{ ...felis, loading: true }] })
    rerender(
      <ApexAssistantRuntime config={loadingProps.assistantRunConfig}>
        <CortexWorkspace {...loadingProps} />
      </ApexAssistantRuntime>,
    )
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Loading…')).toBeInTheDocument()

    const unavailableProps = workspaceProps({ activeAgent: 'felis', agentsStatus: [{ ...felis, status: 'ollama_unreachable', reason: 'Ollama is offline' }] })
    rerender(
      <ApexAssistantRuntime config={unavailableProps.assistantRunConfig}>
        <CortexWorkspace {...unavailableProps} />
      </ApexAssistantRuntime>,
    )
    expect(within(screen.getByLabelText('Local model lifecycle')).getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('Ollama is offline')).toBeInTheDocument()
  })

  it('shows the active local model auto-unload countdown in the lifecycle card', () => {
    vi.useFakeTimers()
    const { rerender } = renderWorkspace({ activeAgent: 'felis', agentsStatus: [{ ...felis, active: true, idle_unload_remaining_seconds: 300 }] })
    expect(screen.getByText('Auto-unload in 05:00')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(screen.getByText('Auto-unload in 04:59')).toBeInTheDocument()

    const busyProps = workspaceProps({ activeAgent: 'felis', lifecycleBusy: true, agentsStatus: [{ ...felis, active: true, idle_unload_remaining_seconds: 299 }] })
    rerender(
      <ApexAssistantRuntime config={busyProps.assistantRunConfig}>
        <CortexWorkspace {...busyProps} />
      </ApexAssistantRuntime>,
    )
    expect(screen.getByText('In use · auto-unload paused')).toBeInTheDocument()
  })

  it('shows context and reasoning selectors for Felis', async () => {
    const user = userEvent.setup()
    const onLocalContextWindowChange = vi.fn().mockResolvedValue(true)
    const onLocalReasoningModeChange = vi.fn().mockResolvedValue(true)
    renderWorkspace({
      activeAgent: 'felis',
      agentsStatus: [felis],
      onLocalContextWindowChange,
      onLocalReasoningModeChange,
    })

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
    renderWorkspace({
      activeAgent: 'felis',
      agentsStatus: [felis],
      onLocalContextWindowChange,
      onLocalReasoningModeChange,
    })

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
    const { rerender } = renderWorkspace({
      activeAgent: 'felis',
      agentsStatus: [felis],
      onLocalContextWindowChange,
    })

    const contextSelect = screen.getByLabelText('Context window')
    await user.selectOptions(contextSelect, '32768')
    expect(contextSelect).toHaveValue('32768')
    resolveContext(true)
    expect(contextSelect).toHaveValue('32768')

    const refreshedProps = workspaceProps({
      activeAgent: 'felis',
      agentsStatus: [{ ...felis, context_window: 32768 }],
      onLocalContextWindowChange,
    })
    rerender(
      <ApexAssistantRuntime config={refreshedProps.assistantRunConfig}>
        <CortexWorkspace {...refreshedProps} />
      </ApexAssistantRuntime>,
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
    const { rerender } = renderWorkspace({
      activeAgent: 'felis',
      agentsStatus: [felis],
      onLocalContextWindowChange,
    })

    const contextSelect = screen.getByLabelText('Context window')
    await user.selectOptions(contextSelect, '32768')
    expect(contextSelect).toBeDisabled()
    resolveContext(true)
    await waitFor(() => expect(contextSelect).toBeEnabled())
    expect(contextSelect).toHaveValue('32768')

    // Stale authority must not snap the selector back, and the control must
    // remain usable for another change even before refreshed status catches up.
    const staleProps = workspaceProps({
      activeAgent: 'felis',
      agentsStatus: [felis],
      onLocalContextWindowChange,
    })
    rerender(
      <ApexAssistantRuntime config={staleProps.assistantRunConfig}>
        <CortexWorkspace {...staleProps} />
      </ApexAssistantRuntime>,
    )
    expect(contextSelect).toHaveValue('32768')
    expect(contextSelect).toBeEnabled()
    onLocalContextWindowChange.mockResolvedValue(true)
    await user.selectOptions(contextSelect, '4096')
    await waitFor(() => expect(contextSelect).toHaveValue('4096'))
  })

  it('disables local context selection during generation or loading', () => {
    const { rerender } = renderWorkspace({
      activeAgent: 'felis',
      agentsStatus: [felis],
    })
    expect(screen.getByLabelText('Context window')).toBeEnabled()

    const loadingProps = workspaceProps({
      activeAgent: 'felis',
      agentsStatus: [{ ...felis, loading: true }],
    })
    rerender(
      <ApexAssistantRuntime config={loadingProps.assistantRunConfig}>
        <CortexWorkspace {...loadingProps} />
      </ApexAssistantRuntime>,
    )
    expect(screen.getByLabelText('Context window')).toBeDisabled()

    const busyProps = workspaceProps({
      activeAgent: 'felis',
      agentsStatus: [felis],
      lifecycleBusy: true,
    })
    rerender(
      <ApexAssistantRuntime config={busyProps.assistantRunConfig}>
        <CortexWorkspace {...busyProps} />
      </ApexAssistantRuntime>,
    )
    expect(screen.getByLabelText('Context window')).toBeDisabled()
  })

  it('renders agent response markdown elements including headings, bold text, links, code, and tables', () => {
    const markdownContent = [
      '# Cortex Response Header',
      'This contains **bold text**, `inline code`, and a [Documentation Link](https://apex.example/docs).',
      '| Feature | Status |\n| --- | --- |\n| Markdown | Supported |',
    ].join('\n\n')

    render(<AssistantResponseDisplay text={markdownContent} rawMetadata={{}} onOpenRecord={vi.fn()} />)

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
      <AssistantResponseDisplay
        text="A grounded answer with [Google Maps: Cafe](https://maps.google.com/cafe)."
        rawMetadata={{
          metadata: {
            agent: null,
            usage: null,
            timing: null,
            cost: null,
            citations: [{ title: 'Cafe', uri: 'https://maps.google.com/cafe', snippet: null, source: 'google_maps' }],
            grounding: { searchSuggestionsHtml: '<a href="https://www.google.com/search">Search</a>' },
            toolSelection: null,
          },
        }}
        onOpenRecord={vi.fn()}
      />,
    )

    expect(screen.getByRole('region', { name: 'Google Maps sources' })).toHaveTextContent('Google Maps: Cafe')
    const suggestions = screen.getByTitle('Google Search suggestions')
    expect(suggestions).toHaveAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox')
    expect(suggestions).toHaveAttribute('srcdoc', '<a href="https://www.google.com/search">Search</a>')
  })

  it('uses display labels rather than raw cloud provider IDs in response metadata', () => {
    render(
      <AssistantResponseDisplay
        text="Research complete."
        rawMetadata={{
          metadata: {
            agent: {
              key: 'panthera', version: '1.0', provider: 'xai', configuredModel: 'grok-4.5', resolvedModel: 'grok-4.5', requestedEffort: 'high', resolvedEffort: 'high',
            },
            usage: null, timing: null, cost: null, citations: [], grounding: null, toolSelection: null,
          },
        }}
        onOpenRecord={vi.fn()}
      />,
    )

    expect(screen.getByText('SpaceXAI / panthera')).toBeInTheDocument()
    expect(screen.queryByText('xai / panthera')).not.toBeInTheDocument()
  })

  it('renders model-native reasoning options dynamically for the selected cloud model', () => {
    const onEffortChange = vi.fn()
    renderWorkspace({
      activeAgent: 'panthera',
      pantheraModel: 'gpt-5.6-luna',
      cloudEffort: 'medium',
      agentsStatus: [panthera],
      onEffortChange,
    })

    const effortSelect = screen.getByLabelText('Reasoning effort')
    expect(effortSelect).toHaveValue('medium')
    expect(screen.getByRole('option', { name: 'None' })).toHaveValue('none')
    expect(screen.getByRole('option', { name: 'Minimal' })).toHaveValue('minimal')
    expect(screen.getByRole('option', { name: 'Low' })).toHaveValue('low')
    expect(screen.getByRole('option', { name: 'Medium' })).toHaveValue('medium')
    expect(screen.getByRole('option', { name: 'High' })).toHaveValue('high')
    expect(screen.getByRole('option', { name: 'Extra High' })).toHaveValue('xhigh')
  })

  it('renders None and High labels for local Felis reasoning mode', () => {
    renderWorkspace({
      activeAgent: 'felis',
      felisModel: 'gemma-4-E2B-Q4_K_M.gguf',
      agentsStatus: [felis],
    })

    const reasoningSelect = screen.getByLabelText('Reasoning')
    expect(reasoningSelect).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'None' })).toHaveValue('none')
    expect(screen.getByRole('option', { name: 'High' })).toHaveValue('focused')
    expect(screen.queryByRole('option', { name: 'Focused' })).not.toBeInTheDocument()
  })
})
