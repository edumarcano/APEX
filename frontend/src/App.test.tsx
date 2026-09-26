import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState, type ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AgentKey, TelemetrySnapshot, ToolCatalog } from './types/telemetry'
import type { RuntimeSettings, SettingsResponse } from './types/settings'
import { BASE_SETTINGS, buildSettingsResponse } from './test/settingsFixtures'

const appMocks = vi.hoisted(() => ({
  initialAgent: 'apex' as AgentKey,
  devModeActive: false,
  demoModeActive: false,
  refreshAgentsStatus: vi.fn().mockResolvedValue(undefined),
  queryAgent: vi.fn().mockResolvedValue(undefined),
  clearCortexSession: vi.fn(),
  loadLocalModel: vi.fn().mockResolvedValue(true),
  unloadLocalModel: vi.fn().mockResolvedValue(true),
  verifyCloudAgent: vi.fn().mockResolvedValue(true),
  applyBootSettings: vi.fn(),
  markReminderAsRead: vi.fn().mockResolvedValue(undefined),
  refreshReminders: vi.fn().mockResolvedValue(undefined),
  createReminder: vi.fn().mockResolvedValue('synced'),
  getReminderTask: vi.fn(),
  listCompletedReminders: vi.fn().mockResolvedValue({ items: [], source_state: 'live' }),
  updateReminderTask: vi.fn(),
  deleteReminderTask: vi.fn(),
  reopenReminderTask: vi.fn(),
  activate: vi.fn(),
  deactivate: vi.fn(),
  activated: true,
  noModels: false,
  settingsPanelApplied: null as unknown,
  marketSymbols: null as string[] | null,
  marketEnabled: false,
  telemetrySnapshot: null as TelemetrySnapshot | null,
  telemetryRefreshingAll: false,
  telemetryRefreshingConnectors: new Set<string>(),
  requestOperation: vi.fn().mockResolvedValue('proceed'),
  toolPreflight: vi.fn(),
  refreshAll: vi.fn().mockResolvedValue(null),
  refreshAllWithOutcome: vi.fn().mockResolvedValue({
    kind: 'failure',
    snapshot: null,
    error: 'refresh failed',
  }),
  refreshConnector: vi.fn().mockResolvedValue(undefined),
  loadLatest: vi.fn().mockResolvedValue(null),
  triggerSynthesis: vi.fn().mockResolvedValue(undefined),
  generateFromSnapshot: vi.fn().mockResolvedValue(undefined),
  speak: vi.fn(),
  weatherSnapshot: null as {
    modules: {
      weather: {
        status: string
        data: { temp_f: number; condition?: string }
        display_text: string
      }
    }
  } | null,
}))

vi.mock('./components/ApexLogo', () => ({
  ApexLogo: ({ reminderPulseCount }: { reminderPulseCount?: number }) => (
    <output data-testid="reminder-pulse-count">{reminderPulseCount ?? 0}</output>
  ),
}))
vi.mock('./components/CelestialBackground', () => ({ CelestialBackground: () => null }))
vi.mock('./components/CalendarEventList', () => ({ CalendarEventList: () => null }))
vi.mock('./components/FootballFixtureList', () => ({ FootballFixtureList: () => null }))
vi.mock('./components/MarketTickerCard', () => ({
  MarketTickerCard: ({ isLoading }: { isLoading?: boolean }) => (
    <output data-testid="market-loading-state">{isLoading ? 'loading' : 'idle'}</output>
  ),
}))
vi.mock('./components/PreflightDialog', () => ({ PreflightDialog: () => null }))
vi.mock('./components/ReminderListRow', () => ({ ReminderListRow: () => null }))
vi.mock('./components/ReminderQuickAdd', () => ({
  ReminderQuickAdd: ({ onSave }: { onSave: (text: string) => Promise<unknown> }) => (
    <button type="button" onClick={() => void onSave('Call the dentist')}>
      Add reminder
    </button>
  ),
}))
vi.mock('./components/TelemetryCard', () => ({
  TelemetryCard: ({
    title,
    headerAction,
    compactValue,
    onRefresh,
    children,
  }: {
    title?: string
    headerAction?: ReactNode
    compactValue?: ReactNode
    onRefresh?: () => void
    children?: ReactNode
  }) => title === 'Reminders' ? (
    <>
      {headerAction}
      <button type="button" aria-label="Refresh Reminders" onClick={onRefresh}>
        {children}
      </button>
    </>
  ) : title === 'Weather' ? (
    <>
      {headerAction}
      <span data-testid="weather-compact-value">{compactValue}</span>
      {children}
    </>
  ) : null,
}))
vi.mock('./components/VoiceSignalGlyph', () => ({ VoiceSignalGlyph: () => null }))
vi.mock('./components/SettingsPanel', () => ({
  default: ({ onApplied }: { onApplied: unknown }) => {
    appMocks.settingsPanelApplied = onApplied
    return null
  },
}))
vi.mock('./components/SystemDiagnostics', () => ({
  SystemDiagnostics: ({ workspaceNavigation }: { workspaceNavigation?: ReactNode }) => (
    <>{workspaceNavigation}</>
  ),
}))
vi.mock('./components/CortexWorkspace', () => ({
  CortexWorkspace: ({
    activeAgent,
    devModeActive,
    sandboxMode,
    onLocalContextWindowChange,
    onHostedToolChange,
    onSandboxModeChange,
    toolCatalog,
    actions,
  }: {
    activeAgent: AgentKey
    devModeActive: boolean
    sandboxMode: boolean
    onLocalContextWindowChange: (contextWindow: number) => Promise<boolean>
    onHostedToolChange: (tool: 'google_search' | 'google_maps', enabled: boolean) => void
    onSandboxModeChange: (enabled: boolean) => void
    toolCatalog: ToolCatalog | null
    actions?: { pendingCount: number }
  }) => {
    const authoritativeContextWindow = toolCatalog?.context_window ?? null
    const [selectedContextWindow, setSelectedContextWindow] = useState(authoritativeContextWindow)
    const [pendingTarget, setPendingTarget] = useState<number | null>(null)
    useEffect(() => {
      if (pendingTarget !== null) {
        if (authoritativeContextWindow === pendingTarget) {
          setPendingTarget(null)
          setSelectedContextWindow(authoritativeContextWindow)
        }
        return
      }
      setSelectedContextWindow(authoritativeContextWindow)
    }, [authoritativeContextWindow, pendingTarget])
    const handleContextWindowChange = async (contextWindow: number): Promise<void> => {
      const rollbackContextWindow =
        pendingTarget ?? authoritativeContextWindow
      setSelectedContextWindow(contextWindow)
      setPendingTarget(contextWindow)
      try {
        const persisted = await onLocalContextWindowChange(contextWindow)
        if (!persisted) {
          setPendingTarget(null)
          setSelectedContextWindow(rollbackContextWindow)
        }
      } catch {
        setPendingTarget(null)
        setSelectedContextWindow(rollbackContextWindow)
      }
    }
    return (
      <div>
        <output data-testid="active-agent">{activeAgent}</output>
        <output data-testid="provider-hosted-tools">
          {toolCatalog?.provider_hosted_tools.join(',') ?? ''}
        </output>
        <output data-testid="catalog-context-window">
          {toolCatalog?.context_window ?? ''}
        </output>
        <output data-testid="actions-pending-count">
          {actions?.pendingCount ?? 0}
        </output>
        {toolCatalog?.context_window !== null ? (
          <select
            aria-label="Context window"
            value={String(selectedContextWindow ?? '')}
            onChange={(event) => {
              void handleContextWindowChange(Number(event.target.value))
            }}
          >
            <option value="16384">16K</option>
            <option value="32768">32K</option>
          </select>
        ) : (
          <button type="button" onClick={() => onHostedToolChange('google_search', true)}>
            Enable Google Search
          </button>
        )}
        {devModeActive ? (
          <input
            aria-label="Sandbox mode"
            type="checkbox"
            checked={sandboxMode}
            onChange={(event) => onSandboxModeChange(event.target.checked)}
          />
        ) : null}
      </div>
    )
  },
}))

vi.mock('./hooks/useApexData', () => ({
  useApexData: () => ({
    activeReminders: [],
    createReminder: appMocks.createReminder,
    demoModeActive: appMocks.demoModeActive,
    devModeActive: appMocks.devModeActive,
    agentQueriesEnabled: true,
    marketEnabled: appMocks.marketEnabled,
    defaultAgent: 'apex' as AgentKey,
    agentInitialSelection: {
      runtime: 'cloud',
      agent: 'apex' as AgentKey,
      modelId: 'deepseek/deepseek-v4-flash-0731',
      effort: 'low',
    },
    briefingDefaultMode: 'flash',
    voiceMode: 'automatic',
    markReminderAsRead: appMocks.markReminderAsRead,
    getReminderTask: appMocks.getReminderTask,
    listCompletedReminders: appMocks.listCompletedReminders,
    updateReminderTask: appMocks.updateReminderTask,
    deleteReminderTask: appMocks.deleteReminderTask,
    reopenReminderTask: appMocks.reopenReminderTask,
    refreshReminders: appMocks.refreshReminders,
    status: 'success',
    applyBootSettings: appMocks.applyBootSettings,
  }),
}))
vi.mock('./hooks/useAppActivation', async () => {
  const { useState } = await import('react')
  return {
    useAppActivation: () => {
      const [, setRevision] = useState(0)
      return {
        activated: appMocks.activated,
        activate: () => {
          appMocks.activate()
          appMocks.activated = true
          setRevision((revision) => revision + 1)
        },
        deactivate: () => {
          appMocks.deactivate()
          appMocks.activated = false
          setRevision((revision) => revision + 1)
        },
      }
    },
  }
})
vi.mock('./hooks/useBriefingPipeline', () => ({
  useBriefingPipeline: () => ({
    briefing: '',
    status: 'idle',
    isSpeaking: false,
    pipelineState: null,
    active_tts_engine: 'google',
    system_load_throttled: false,
    failedConnectors: [],
    connectorHealth: [],
    synthesisProvider: null,
    synthesisAgent: null,
    synthesisFallbackReason: null,
    insights: [],
    triggerSynthesis: appMocks.triggerSynthesis,
    generateFromSnapshot: appMocks.generateFromSnapshot,
  }),
}))
vi.mock('./hooks/useCortex', () => ({
  useCortex: () => ({
    cortexHistory: [],
    isCortexQuerying: false,
    activeQueryAgent: null,
    cortexLatestTrace: [],
    cortexError: null,
    cortexContextUsage: null,
    cortexAgent: {
      key: 'apex' as AgentKey,
      display_name: 'Apex Agent',
      description: 'Native assistant.',
      selected_model: 'deepseek/deepseek-v4-flash-0731',
      model_catalog: [{
        model_id: 'deepseek/deepseek-v4-flash-0731',
        display_name: 'DeepSeek V4 Flash',
        provider: 'openrouter',
        runtime: 'cloud',
        stability: 'stable',
        hosted_capabilities: [],
      }],
    },
    modelCatalog: appMocks.noModels ? [] : [{
      model_id: 'deepseek/deepseek-v4-flash-0731',
      display_name: 'DeepSeek V4 Flash',
      provider: 'openrouter',
      runtime: 'cloud',
      stability: 'stable',
      hosted_capabilities: [],
    }],
    cortexAgentHydrated: true,
    queryAgent: appMocks.queryAgent,
    isLocalModelActionPending: false,
    verifyingCloudAgent: null,
    loadLocalModel: appMocks.loadLocalModel,
    unloadLocalModel: appMocks.unloadLocalModel,
    verifyCloudAgent: appMocks.verifyCloudAgent,
    refreshAgentsStatus: appMocks.refreshAgentsStatus,
    clearCortexSession: appMocks.clearCortexSession,
  }),
}))
vi.mock('./hooks/useMarketData', () => ({
  useMarketData: (_enabled: boolean, _revision: number | null, symbols: string[] | null) => {
    appMocks.marketSymbols = symbols
    return { data: null, isLoading: false }
  },
}))
vi.mock('./hooks/usePreflight', () => ({
  usePreflight: () => ({
    requestOperation: appMocks.requestOperation,
    dialogOpen: false,
    pendingOperation: null,
    warnings: [],
    blockers: [],
    isChecking: false,
    error: null,
    resolveDialog: vi.fn(),
  }),
}))
vi.mock('./hooks/useSystemDiagnostics', () => ({
  useSystemDiagnostics: () => ({ diagnostics: {}, status: 'idle' }),
}))
vi.mock('./hooks/useTelemetrySnapshot', () => ({
  useTelemetrySnapshot: () => ({
    snapshot: appMocks.telemetrySnapshot ?? appMocks.weatherSnapshot,
    isRefreshingAll: appMocks.telemetryRefreshingAll,
    refreshingConnectors: appMocks.telemetryRefreshingConnectors,
    refreshAll: appMocks.refreshAll,
    refreshAllWithOutcome: appMocks.refreshAllWithOutcome,
    refreshConnector: appMocks.refreshConnector,
    loadLatest: appMocks.loadLatest,
  }),
}))
vi.mock('./hooks/useToolPreflight', () => ({
  useToolPreflight: (options: unknown) => {
    appMocks.toolPreflight(options)
    return {
      estimate: null,
      isLoading: false,
      error: null,
    }
  },
}))
vi.mock('./hooks/useVoiceDelivery', () => ({
  useVoiceDelivery: () => ({
    isSpeaking: false,
    lastManualEngine: null,
    error: null,
    speak: appMocks.speak,
  }),
}))

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function catalogFor(
  agent: AgentKey,
  googleSearchEnabled = false,
): ToolCatalog {
  return {
    agent,
    groups: [],
    tools: [],
    profiles: [{
      id: 'no_tools',
      name: 'No APEX Tools',
      description: 'No live tools.',
      tool_names: [],
      built_in: true,
      dynamic: false,
    }],
    default_profile_id: 'no_tools',
    default_profile_name: 'No APEX Tools',
    default_selected_tool_names: [],
    provider_hosted_tools: googleSearchEnabled ? ['google_search'] : [],
    context_window: null,
    reserved_response_tokens: null,
  }
}

function settingsResponse(
  googleSearchEnabled = false,
  contextWindow = 16384,
  sandboxMode = false,
): Response {
  return new Response(JSON.stringify({
    schema_version: 19,
    settings: {
      user_designation: '',
      agent_display_name: '',
      features: {
        weather: false,
        sports: false,
        news: false,
        email: false,
        calendar: false,
        market: false,
      },
      modules: { football: false, f1: false },
      football: { teams: [] },
      market: { symbols: [] },
      ask_apex: {
        enabled: true,
        selected_model: 'deepseek/deepseek-v4-flash-0731',
        sandbox_mode: sandboxMode,
        cloud: {
          last_model: 'deepseek/deepseek-v4-flash-0731',
          effort: 'low',
          personal_context_enabled: false,
          hosted_tools: {
            google_search: googleSearchEnabled,
            google_maps: false,
          },
        },
        local: {
          last_model: 'gemma-4-E2B-Q4_K_M.gguf',
          context_window: contextWindow,
          reasoning_mode: 'none',
          personal_context_enabled: false,
        },
      },
      tool_profiles: {
        custom_profiles: [],
        default_profile_by_runtime: {},
      },
      briefing: { default_mode: 'flash' },
      voice: { engine: 'google', gender: 'female', mode: 'automatic' },
      mcp: {
        enabled: false,
        servers: {
          github: { enabled: false },
          brave: { enabled: false },
          alphavantage: { enabled: false },
        },
      },
      llama_cpp: {
        enabled: false,
        managed: false,
        host: 'http://127.0.0.1:11434',
        executable_path: '',
        preset_path: '',
      },
    },
    local_file_present: false,
    local_override_active: false,
    load_warning: null,
    dev_mode_active: false,
    demo_mode_active: false,
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function applySavedSettings(response: SettingsResponse, previousSettings: RuntimeSettings): Promise<void> {
  if (typeof appMocks.settingsPanelApplied !== 'function') {
    throw new Error('SettingsPanel has not supplied an onApplied callback.')
  }
  return (appMocks.settingsPanelApplied as (saved: SettingsResponse, previous: RuntimeSettings) => Promise<void>)(response, previousSettings)
}

async function selectWorkspace(user: ReturnType<typeof userEvent.setup>, name: string): Promise<void> {
  await user.click(screen.getByRole('button', { name: 'Workspace' }))
  await user.click(within(screen.getByRole('menu', { name: 'Workspace' })).getByRole('menuitemradio', { name }))
}

describe('App catalog-affecting settings', () => {
  afterEach(() => {
    appMocks.initialAgent = 'apex'
    appMocks.devModeActive = false
    appMocks.marketEnabled = false
    appMocks.activated = true
    appMocks.settingsPanelApplied = null
    appMocks.telemetryRefreshingAll = false
    appMocks.telemetryRefreshingConnectors = new Set<string>()
    appMocks.weatherSnapshot = null
    appMocks.refreshConnector.mockClear()
    appMocks.applyBootSettings.mockClear()
    appMocks.toolPreflight.mockClear()
    vi.restoreAllMocks()
  })

  it('refreshes the Apex catalog after enabling Google Search', async () => {
    const user = userEvent.setup()
    const settingsPatch = deferred<Response>()
    const catalogRequests: Array<string | null> = []
    let apexCatalogRequests = 0

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const modelId = url.searchParams.get('model_id')
          catalogRequests.push(modelId)
          const googleSearchEnabled = modelId === 'deepseek/deepseek-v4-flash-0731' && apexCatalogRequests++ > 0
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor('apex', googleSearchEnabled)),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ))
        }
        if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
          return settingsPatch.promise
        }
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    render(<App />)

    await selectWorkspace(user, 'Cortex')
    await waitFor(() => expect(catalogRequests).toContain('deepseek/deepseek-v4-flash-0731'))
    await waitFor(() => expect(screen.getByTestId('active-agent')).toHaveTextContent('apex'))
    expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('')

    await user.click(screen.getByRole('button', { name: 'Enable Google Search' }))
    expect(catalogRequests.filter((modelId) => modelId === 'deepseek/deepseek-v4-flash-0731')).toHaveLength(1)

    settingsPatch.resolve(settingsResponse(true))

    await waitFor(() => {
      expect(catalogRequests.filter((modelId) => modelId === 'deepseek/deepseek-v4-flash-0731')).toHaveLength(2)
      expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('google_search')
    })
  })

  it('preserves the Home assistant contract and disables preflight in Inbox', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))))
    appMocks.toolPreflight.mockClear()

    render(<App />)
    const homeContract = appMocks.toolPreflight.mock.lastCall?.[0] as { effort: string | null }
    expect(homeContract.effort).toBeNull()

    await selectWorkspace(user, 'Inbox')
    await waitFor(() => expect(appMocks.toolPreflight.mock.lastCall?.[0]).toMatchObject({
      effort: homeContract.effort,
      enabled: false,
    }))
  })

  it('switches peer workspaces from a single header menu without a Standby peer', async () => {
    const user = userEvent.setup()
    render(<App />)

    const chip = screen.getByRole('button', { name: 'Workspace' })
    expect(chip).toHaveTextContent('Overview')
    expect(chip).toHaveAttribute('aria-haspopup', 'menu')
    expect(chip).toHaveAttribute('aria-expanded', 'false')

    await user.click(chip)
    const menu = screen.getByRole('menu', { name: 'Workspace' })
    expect(within(menu).getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual([
      'Inbox', 'Overview', 'Briefing', 'Cortex',
    ])
    expect(within(menu).getByRole('menuitemradio', { name: 'Overview' })).toHaveAttribute('aria-checked', 'true')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(chip).toHaveFocus()

    await user.click(chip)
    await user.click(document.body)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await selectWorkspace(user, 'Inbox')
    expect(chip).toHaveTextContent('Inbox')
    expect(chip).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it('refreshes the current catalog after toggling sandbox mode', async () => {
    appMocks.devModeActive = true
    const user = userEvent.setup()
    const catalogRequests: Array<string | null> = []
    let sandboxPatch: Record<string, unknown> | null = null

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const modelId = url.searchParams.get('model_id')
          catalogRequests.push(modelId)
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor('apex')),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ))
        }
        if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
          sandboxPatch = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(settingsResponse(false, 16384, true))
        }
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    render(<App />)

    await selectWorkspace(user, 'Cortex')
    await waitFor(() => expect(catalogRequests).toContain('deepseek/deepseek-v4-flash-0731'))

    await user.click(screen.getByRole('checkbox', { name: 'Sandbox mode' }))

    await waitFor(() => {
      expect(sandboxPatch).toEqual({ ask_apex: { sandbox_mode: true } })
      expect(catalogRequests.filter((modelId) => modelId === 'deepseek/deepseek-v4-flash-0731')).toHaveLength(2)
    })
  })

  it('refreshes action proposals when an assistant response is received', async () => {
    const user = userEvent.setup()
    const actionProposal = {
      action_id: 'action-123',
      proposal: {
        agent_key: 'apex',
        capability_name: 'remember_personal_context',
        arguments: { text: 'Prefers tea over coffee' },
        target: 'Remember personal context',
        risk: 'write',
        summary: 'Approve Remember personal context',
        proposed_at: '2026-08-18T12:00:00Z',
        expires_at: '2026-08-19T12:00:00Z',
        proposal_hash: 'a'.repeat(64),
      },
      status: 'proposed',
      version: 0,
      updated_at: '2026-08-18T12:00:00Z',
    }

    let actionsRequested = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor('apex')),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ))
        }
        if (url.pathname.endsWith('/api/v1/actions')) {
          actionsRequested += 1
          const status = url.searchParams.get('status')
          if (status === 'proposed') {
            return Promise.resolve(new Response(
              JSON.stringify([actionProposal]),
              { status: 200, headers: { 'Content-Type': 'application/json' } },
            ))
          }
          return Promise.resolve(new Response(
            JSON.stringify([actionProposal]),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ))
        }
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    render(<App />)

    await selectWorkspace(user, 'Cortex')
    await waitFor(() => expect(actionsRequested).toBeGreaterThan(0))
    await waitFor(() => {
      expect(screen.getByTestId('actions-pending-count')).toHaveTextContent('1')
    })
  })
})

describe('App market loading feedback', () => {
  afterEach(() => {
    appMocks.marketEnabled = false
    appMocks.telemetryRefreshingAll = false
    appMocks.telemetryRefreshingConnectors = new Set<string>()
  })

  it('shows loading only while Market participates in telemetry refresh', () => {
    appMocks.marketEnabled = true
    appMocks.telemetryRefreshingAll = true
    const { rerender } = render(<App />)
    expect(screen.getByTestId('market-loading-state')).toHaveTextContent('loading')

    appMocks.telemetryRefreshingAll = false
    appMocks.telemetryRefreshingConnectors = new Set(['market'])
    rerender(<App />)
    expect(screen.getByTestId('market-loading-state')).toHaveTextContent('loading')

    appMocks.telemetryRefreshingConnectors = new Set(['calendar'])
    rerender(<App />)
    expect(screen.getByTestId('market-loading-state')).toHaveTextContent('idle')
  })
})

describe('App Market settings refresh', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.settingsPanelApplied = null
    appMocks.refreshConnector.mockClear()
    appMocks.applyBootSettings.mockClear()
  })

  it('refreshes changed Market settings only while the application is activated', async () => {
    const { rerender } = render(<App />)
    const baseline = structuredClone(BASE_SETTINGS)
    const unrelated = structuredClone(baseline)
    unrelated.voice.mode = 'off'

    await act(async () => {
      await applySavedSettings(buildSettingsResponse(unrelated), baseline)
    })
    expect(appMocks.refreshConnector).not.toHaveBeenCalled()

    const changedSymbols = structuredClone(baseline)
    changedSymbols.market.symbols = ['SPY', 'AAPL']
    await act(async () => {
      await applySavedSettings(buildSettingsResponse(changedSymbols), baseline)
    })
    expect(appMocks.refreshConnector).toHaveBeenCalledWith('market', { force: true })
    expect(appMocks.marketSymbols).toEqual(['SPY', 'AAPL'])

    const disabled = structuredClone(changedSymbols)
    disabled.features.market = false
    await act(async () => {
      await applySavedSettings(buildSettingsResponse(disabled), changedSymbols)
    })
    expect(appMocks.applyBootSettings).toHaveBeenLastCalledWith(expect.objectContaining({ marketEnabled: false }))
    expect(appMocks.refreshConnector).toHaveBeenCalledTimes(2)

    appMocks.activated = false
    rerender(<App />)
    const inactiveChange = structuredClone(disabled)
    inactiveChange.market.symbols = ['QQQ']
    await act(async () => {
      await applySavedSettings(buildSettingsResponse(inactiveChange), disabled)
    })
    expect(appMocks.refreshConnector).toHaveBeenCalledTimes(2)
  })
})

describe('App weather attribution', () => {
  it('keeps Open-Meteo, GeoNames, licence, and adaptation credit visible in the weather header', () => {
    appMocks.weatherSnapshot = {
      modules: {
        weather: {
          status: 'healthy',
          data: { temp_f: 72, condition: 'mainly clear' },
          display_text: 'Current temperature is 72 degrees with mainly clear.',
        },
      },
    }
    render(<App />)

    expect(screen.getByText('Weather by')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open-Meteo' })).toHaveAttribute(
      'href',
      'https://open-meteo.com/',
    )
    expect(screen.getByRole('link', { name: 'GeoNames' })).toHaveAttribute(
      'href',
      'https://www.geonames.org/',
    )
    expect(screen.getByRole('link', { name: 'CC BY 4.0' })).toHaveAttribute(
      'href',
      'https://creativecommons.org/licenses/by/4.0/',
    )
    expect(screen.getByText(/adapted by APEX/)).toBeInTheDocument()
    expect(screen.getAllByText('Mainly Clear')).toHaveLength(1)
  })
})

describe('App reminder feedback', () => {
  it('pulses the logo after an accepted reminder save', async () => {
    const user = userEvent.setup()

    render(<App />)

    expect(screen.getByTestId('reminder-pulse-count')).toHaveTextContent('0')
    await user.click(screen.getByRole('button', { name: 'Add reminder' }))

    await waitFor(() => expect(screen.getByTestId('reminder-pulse-count')).toHaveTextContent('1'))
    expect(appMocks.createReminder).toHaveBeenCalledWith('Call the dentist')
  })

  it('opens completed reminders from the panel header without renaming the panel', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Completed reminders' }))

    expect(await screen.findByRole('heading', { name: 'Completed reminders' })).toBeInTheDocument()
    expect(appMocks.listCompletedReminders).toHaveBeenCalledOnce()
  })
})

describe('App contextual voice cues', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.demoModeActive = false
    appMocks.weatherSnapshot = null
    appMocks.telemetrySnapshot = null
    appMocks.refreshAllWithOutcome.mockReset().mockResolvedValue({
      kind: 'failure',
      snapshot: null,
      error: 'refresh failed',
    })
    appMocks.generateFromSnapshot.mockReset().mockResolvedValue(undefined)
    appMocks.triggerSynthesis.mockReset().mockResolvedValue(undefined)
    appMocks.loadLatest.mockReset().mockResolvedValue(null)
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubAppFetch(events: string[]): void {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/voice/cue')) {
        const body = JSON.parse(String(init?.body)) as { cue: string }
        events.push(`cue:${body.cue}`)
      }
      if (url.pathname.endsWith('/briefings/targets')) {
        return Promise.resolve(new Response(JSON.stringify([
          {
            mode: 'flash',
            label: 'Flash',
            description: 'Flash briefing',
            model_id: 'gemma-4-E2B-Q4_K_M.gguf',
            model_display_name: 'Gemma 4 E2B',
            provider: 'llama.cpp',
            runtime: 'local',
            status: 'available',
            reason: null,
            pricing: null,
          },
        ]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
  }

  function createTelemetrySnapshot(
    collectedAt: string = new Date().toISOString(),
    modules: TelemetrySnapshot['modules'] = {
      weather: {
        name: 'weather',
        status: 'healthy',
        freshness: 'live',
        reason_code: 'ok',
        observed_at: collectedAt,
        display_text: 'Clear',
        data: {},
      },
    },
  ): TelemetrySnapshot {
    return {
      snapshot_id: 'snap-current',
      collected_at: collectedAt,
      modules,
      sync_health_score: 100,
      connector_health: [],
      failed_connectors: [],
    }
  }

  it('uses only the loading greeting when refresh fills missing telemetry', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Overview' }))

    await waitFor(() => {
      expect(events).toEqual(['refresh', 'cue:activation_loading'])
    })
  })

  it('loads a fresh current snapshot before choosing the single ready welcome', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    appMocks.loadLatest.mockResolvedValue(createTelemetrySnapshot())
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Overview' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_ready']))
    expect(appMocks.loadLatest).toHaveBeenCalledOnce()
  })

  it('uses the latest fresh snapshot when the local snapshot has expired', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    appMocks.telemetrySnapshot = createTelemetrySnapshot(
      new Date(Date.now() - 5 * 60 * 1000 - 1000).toISOString(),
      {
        weather: {
          name: 'weather',
          status: 'healthy',
          freshness: 'live',
          reason_code: 'ok',
          observed_at: new Date().toISOString(),
          display_text: 'Clear',
          data: {},
        },
      },
    )
    appMocks.loadLatest.mockResolvedValue(createTelemetrySnapshot())
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Overview' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_ready']))
    expect(appMocks.loadLatest).toHaveBeenCalledOnce()
  })

  it('orders the activation refresh failure follow-up and skips it on conflict', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'failure', snapshot: null, error: 'network down' }
    })

    const firstRender = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Overview' }))
    await waitFor(() => {
      expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_refresh_failed'])
    })

    firstRender.unmount()
    events.length = 0
    appMocks.activated = false
    appMocks.refreshAllWithOutcome.mockResolvedValue({
      kind: 'conflict',
      snapshot: null,
      error: 'A telemetry refresh is already in progress',
    })
    const secondUser = userEvent.setup()
    render(<App />)
    await secondUser.click(screen.getByRole('button', { name: 'Start Overview' }))
    await waitFor(() => expect(events).toEqual(['cue:activation_loading']))
  })

  it('uses standby wording rather than refresh-failed wording when no fresh module is available', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot(new Date().toISOString(), {}) }
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Overview' }))

    await waitFor(() => {
      expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_no_fresh_telemetry'])
    })
  })

})

describe('App Home states', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.noModels = false
    appMocks.weatherSnapshot = null
    appMocks.deactivate.mockClear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubHomeFetch(posts: string[]): void {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      if (init?.method === 'POST') posts.push(url.pathname)
      if (url.pathname.endsWith('/briefing-sessions')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (url.pathname.endsWith('/cortex/conversations')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
  }

  it('offers Overview and Briefing from Standby without a command panel or composer', () => {
    appMocks.activated = false
    stubHomeFetch([])
    render(<App />)

    expect(screen.getByRole('button', { name: 'Start Overview' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Start Briefing with Daily' })).toBeEnabled()
    expect(screen.queryByRole('region', { name: 'Home command rail' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('shows telemetry in Overview without a model, composer, or briefing controls', () => {
    appMocks.noModels = true
    appMocks.weatherSnapshot = {
      modules: { weather: { status: 'healthy', data: { temp_f: 72 }, display_text: 'Current temperature is 72 degrees.' } },
    }
    stubHomeFetch([])
    render(<App />)

    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByTestId('weather-compact-value')).not.toBeEmptyDOMElement()
    expect(screen.getByRole('button', { name: 'Refresh Reminders' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Briefing controls' })).not.toBeInTheDocument()
  })

  it('switches between Overview and Briefing from the header menu without generating', async () => {
    const user = userEvent.setup()
    const posts: string[] = []
    stubHomeFetch(posts)
    render(<App />)

    await selectWorkspace(user, 'Briefing')
    expect(screen.getByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Standby' })).not.toBeInTheDocument()

    await selectWorkspace(user, 'Overview')
    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
  })

  it('activates into the chosen Home peer from Standby without generating a briefing', async () => {
    appMocks.activated = false
    appMocks.activate.mockClear()
    const user = userEvent.setup()
    const posts: string[] = []
    stubHomeFetch(posts)
    render(<App />)

    expect(screen.getByRole('region', { name: 'Standby' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveTextContent('Overview')

    await selectWorkspace(user, 'Briefing')
    await waitFor(() => expect(appMocks.activate).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveTextContent('Briefing')
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
  })

  it('starts Overview from the Standby floating action', async () => {
    appMocks.activated = false
    const user = userEvent.setup()
    stubHomeFetch([])
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Start Overview' }))
    expect(await screen.findByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Standby' })).not.toBeInTheDocument()
  })
})

describe('App briefing session flow', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.demoModeActive = false
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('generates from Standby, opens the saved artifact as the conversation opening, and preserves the draft across views', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const user = userEvent.setup()
    const sessionId = '00000000-0000-4000-8000-000000000071'
    const conversationId = '00000000-0000-4000-8000-000000000072'
    const userMessageId = '00000000-0000-4000-8000-000000000073'
    const assistantMessageId = '00000000-0000-4000-8000-000000000074'
    const sessionSummary = {
      id: sessionId,
      profile_id: 'daily',
      model_id: 'deepseek/deepseek-v4-flash-0731',
      conversation_id: conversationId,
      run_id: '00000000-0000-4000-8000-000000000075',
      run_status: 'running',
      created_at: '2026-09-25T13:00:00Z',
      presented_at: null,
    }
    const sessionDetail = () => ({
      id: sessionId,
      conversation_id: conversationId,
      opening_message_id: assistantMessageId,
      run_id: sessionSummary.run_id,
      run_status: runStatus,
      configuration: {
        profile: { id: 'daily', label: 'Daily', purpose: 'A concise view of current information.', definition_version: 2 },
        model: { model_id: sessionSummary.model_id, provider: 'openrouter', runtime: 'cloud', reasoning: 'low', context_window: 16384, local_reasoning_mode: null },
        origin: 'hud',
        execution_kind: 'model',
      },
      artifact: runStatus === 'completed' ? {
        schema_version: 1,
        session_id: sessionId,
        created_at: '2026-09-25T13:01:00Z',
        sections: [{ id: 'section-1', title: 'Today', items: [{
          id: 'item-1', category: 'observation', title: 'Morning travel', body: 'Leave early for the 9 AM meeting.', evidence_ids: [], record_references: [],
        }] }],
        coverage: [],
        limitations: [],
      } : null,
      evidence_count: 0,
      evidence_ids: [],
      created_at: '2026-09-25T13:00:00Z',
      presented_at: presentedAt,
      speech_status: 'not_requested',
    })
    let runStatus: 'running' | 'completed' = 'running'
    let presentedAt: string | null = null
    let admissionBody: Record<string, unknown> | null = null
    let admissions = 0
    let detailReads = 0
    let presentationWrites = 0
    let cancellationWrites = 0
    let speechReads = 0
    let speechPrepares = 0
    let speechPlays = 0
    let speechStatus: 'not_requested' | 'preparing' | 'ready' = 'not_requested'
    const speechResponse = () => ({
      session_id: sessionId,
      artifact_sha256: 'canonical-artifact-digest',
      status: speechStatus,
      error_code: null,
      engine: 'google',
    })
    class VisibleIntersectionObserver {
      private readonly callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) { this.callback = callback }
      observe(target: Element): void {
        const rect = target.getBoundingClientRect()
        this.callback([{
          target,
          isIntersecting: true,
          intersectionRatio: 1,
          boundingClientRect: rect,
          intersectionRect: rect,
          rootBounds: null,
          time: 0,
        }], this as unknown as IntersectionObserver)
      }
      disconnect(): void {}
      unobserve(): void {}
      takeRecords(): IntersectionObserverEntry[] { return [] }
    }
    vi.stubGlobal('IntersectionObserver', VisibleIntersectionObserver as unknown as typeof IntersectionObserver)
    appMocks.activated = false
    appMocks.activate.mockClear()
    appMocks.requestOperation.mockClear().mockResolvedValue('proceed')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      const path = url.pathname
      if (path.endsWith('/briefing-sessions') && init?.method === 'POST') {
        admissions += 1
        admissionBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify(sessionSummary), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/briefing-sessions') && init?.method !== 'POST') {
        return new Response(JSON.stringify(admissionBody ? [{ ...sessionSummary, run_status: runStatus }] : []), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}/speech/prepare`)) {
        speechPrepares += 1
        speechStatus = 'preparing'
        return new Response(JSON.stringify(speechResponse()), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}/speech/play`)) {
        speechPlays += 1
        speechStatus = 'ready'
        return new Response(JSON.stringify(speechResponse()), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}/speech/stop`)) {
        speechStatus = 'ready'
        return new Response(JSON.stringify(speechResponse()), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}/speech`)) {
        speechReads += 1
        if (speechStatus === 'preparing' && speechReads > 1) speechStatus = 'ready'
        return new Response(JSON.stringify(speechResponse()), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}/presented`)) {
        presentationWrites += 1
        presentedAt = '2026-09-25T13:02:00Z'
        return new Response(JSON.stringify(sessionDetail()), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${sessionId}`)) {
        detailReads += 1
        return new Response(JSON.stringify(sessionDetail()), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/cortex/runs/${sessionSummary.run_id}/cancel`)) {
        cancellationWrites += 1
        return new Response(JSON.stringify({ status: 'cancelling' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/cortex/conversations/${conversationId}`)) {
        const messages = runStatus === 'completed' ? [
          { id: userMessageId, parent_message_id: null, role: 'user', content: 'Prepare a Daily briefing.', status: 'completed', agent: null, created_at: '2026-09-25T13:00:00Z', updated_at: '2026-09-25T13:00:00Z' },
          { id: assistantMessageId, parent_message_id: userMessageId, role: 'agent', content: 'Saved Daily opening artifact for the morning meeting.', status: 'completed', agent: 'apex', response_metadata: { briefing_session_id: sessionId }, created_at: '2026-09-25T13:01:00Z', updated_at: '2026-09-25T13:01:00Z' },
        ] : []
        return new Response(JSON.stringify({
          id: conversationId,
          title: 'Daily briefing',
          archived_at: null,
          agent: 'apex',
          selected_tool_names: [],
          tool_profile_id: null,
          updated_at: '2026-09-25T13:01:00Z',
          active_leaf_message_id: runStatus === 'completed' ? assistantMessageId : null,
          messages,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/cortex/conversations')) {
        return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/cortex/tool-catalog')) {
        return new Response(JSON.stringify(catalogFor('apex')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Start Briefing with Daily' }))

    await waitFor(() => expect(admissionBody).not.toBeNull())
    expect(appMocks.requestOperation).toHaveBeenCalledWith('generate_briefing_session', expect.objectContaining({
      model_id: 'deepseek/deepseek-v4-flash-0731',
      involves_cloud: true,
    }))
    expect(admissionBody).toMatchObject({ profile_id: 'daily', model_id: 'deepseek/deepseek-v4-flash-0731' })
    expect(appMocks.activate).toHaveBeenCalled()
    await waitFor(() => expect(detailReads).toBeGreaterThan(0))
    expect(screen.getByRole('region', { name: 'Briefing' })).toHaveAttribute('data-layout', 'identity')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()

    await selectWorkspace(user, 'Cortex')
    expect(presentationWrites).toBe(0)
    runStatus = 'completed'
    await selectWorkspace(user, 'Briefing')

    const savedSessions = await screen.findByRole('navigation', { name: 'Saved briefing sessions' })
    await user.click(within(savedSessions).getAllByRole('button')[0])

    const artifact = await screen.findByTestId('briefing-artifact')
    expect(within(artifact).getByText('Morning travel')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Briefing' })).toHaveAttribute('data-layout', 'workspace')
    const prepareSpeech = await screen.findByRole('button', { name: 'Prepare highlights' })
    expect(speechReads).toBeGreaterThan(0)
    expect(speechPlays).toBe(0)
    await user.click(prepareSpeech)
    await waitFor(() => expect(speechPrepares).toBe(1))
    expect(speechPlays).toBe(0)
    await waitFor(() => expect(presentationWrites).toBe(1))
    expect(admissions).toBe(1)

    const composer = await screen.findByRole('textbox')
    await user.type(composer, 'What about traffic?')
    await selectWorkspace(user, 'Inbox')
    await selectWorkspace(user, 'Overview')
    expect(screen.queryByTestId('briefing-artifact')).not.toBeInTheDocument()
    await selectWorkspace(user, 'Briefing')

    expect(await screen.findByTestId('briefing-artifact')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('What about traffic?')
    expect(admissions).toBe(1)
    expect(presentationWrites).toBe(1)
    expect(cancellationWrites).toBe(0)
  }, 10000)
})
