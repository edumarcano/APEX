import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState, type ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AgentKey, ToolCatalog } from './types/telemetry'

const appMocks = vi.hoisted(() => ({
  initialAgent: 'panthera' as AgentKey,
  devModeActive: false,
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
  requestOperation: vi.fn().mockResolvedValue('proceed'),
  refreshAll: vi.fn().mockResolvedValue(null),
  refreshConnector: vi.fn().mockResolvedValue(undefined),
  loadLatest: vi.fn().mockResolvedValue(undefined),
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
vi.mock('./components/BriefingDigest', () => ({ BriefingDigest: () => null }))
vi.mock('./components/CalendarEventList', () => ({ CalendarEventList: () => null }))
vi.mock('./components/FootballFixtureList', () => ({ FootballFixtureList: () => null }))
vi.mock('./components/MarketTickerCard', () => ({ MarketTickerCard: () => null }))
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
vi.mock('./components/SettingsPanel', () => ({ default: () => null }))
vi.mock('./components/HomeCommandRail', () => ({ HomeCommandRail: () => null }))
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
  }: {
    activeAgent: AgentKey
    devModeActive: boolean
    sandboxMode: boolean
    onLocalContextWindowChange: (contextWindow: number) => Promise<boolean>
    onHostedToolChange: (tool: 'google_search' | 'google_maps' | 'x_search', enabled: boolean) => void
    onSandboxModeChange: (enabled: boolean) => void
    toolCatalog: ToolCatalog | null
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
        {activeAgent === 'felis' ? (
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
    demoModeActive: false,
    devModeActive: appMocks.devModeActive,
    agentQueriesEnabled: true,
    marketEnabled: false,
    defaultAgent: appMocks.initialAgent,
    agentInitialSelection: {
      runtime: appMocks.initialAgent === 'felis' ? 'local' : 'cloud',
      agent: appMocks.initialAgent,
      effort: 'focused',
    },
    briefingDefaultMode: 'panthera',
    voiceMode: 'automatic',
    markReminderAsRead: appMocks.markReminderAsRead,
    getReminderTask: appMocks.getReminderTask,
    listCompletedReminders: appMocks.listCompletedReminders,
    updateReminderTask: appMocks.updateReminderTask,
    deleteReminderTask: appMocks.deleteReminderTask,
    reopenReminderTask: appMocks.reopenReminderTask,
    refreshReminders: appMocks.refreshReminders,
    applyBootSettings: appMocks.applyBootSettings,
  }),
}))
vi.mock('./hooks/useAppActivation', () => ({
  useAppActivation: () => ({ activated: true, activate: appMocks.activate }),
}))
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
    agentsStatus: [{
      key: appMocks.initialAgent,
      display_name: `Apex ${appMocks.initialAgent}`,
      runtime: appMocks.initialAgent === 'felis' ? 'local' : 'cloud',
      status: appMocks.initialAgent === 'felis' ? 'available' : 'configured',
      active: true,
      loading: false,
      loaded_model: null,
    }],
    agentsStatusHydrated: true,
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
  useMarketData: () => ({ data: null, isLoading: false }),
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
    snapshot: appMocks.weatherSnapshot,
    isRefreshingAll: false,
    refreshingConnectors: new Set<string>(),
    refreshAll: appMocks.refreshAll,
    refreshConnector: appMocks.refreshConnector,
    loadLatest: appMocks.loadLatest,
  }),
}))
vi.mock('./hooks/useToolPreflight', () => ({
  useToolPreflight: () => ({
    estimate: null,
    isLoading: false,
    error: null,
  }),
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
  contextWindow = 16384,
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
    context_window: agent === 'felis' ? contextWindow : null,
    reserved_response_tokens: agent === 'felis' ? 512 : null,
  }
}

function settingsResponse(
  agent: AgentKey,
  googleSearchEnabled = false,
  contextWindow = 16384,
  sandboxMode = false,
): Response {
  return new Response(JSON.stringify({
    schema_version: 16,
    settings: {
      user_designation: '',
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
        agent,
        sandbox_mode: sandboxMode,
        panthera: {
          model: 'gemini-3.6-flash',
          effort: 'focused',
          hosted_tools: {
            google_search: googleSearchEnabled,
            google_maps: false,
            x_search: false,
          },
        },
        felis: {
          model: 'gemma-4-E2B-Q4_K_M.gguf',
          context_window: contextWindow,
          reasoning_mode: 'none',
        },
      },
      tool_profiles: {
        custom_profiles: [],
        default_profile_by_agent: {},
      },
      briefing: { default_mode: 'panthera' },
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

describe('App catalog-affecting settings', () => {
  afterEach(() => {
    appMocks.initialAgent = 'panthera'
    appMocks.devModeActive = false
    appMocks.weatherSnapshot = null
    vi.restoreAllMocks()
  })

  it('refreshes the current Panthera catalog after enabling Google Search', async () => {
    const user = userEvent.setup()
    const settingsPatch = deferred<Response>()
    const catalogRequests: AgentKey[] = []
    let pantheraCatalogRequests = 0

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const agent = url.searchParams.get('agent') as AgentKey
          catalogRequests.push(agent)
          const googleSearchEnabled =
            agent === 'panthera' && pantheraCatalogRequests++ > 0
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor(agent, googleSearchEnabled)),
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

    await user.click(screen.getByRole('button', { name: 'Cortex' }))
    await waitFor(() => expect(catalogRequests).toContain('panthera'))
    await waitFor(() => expect(screen.getByTestId('active-agent')).toHaveTextContent('panthera'))
    expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('')

    await user.click(screen.getByRole('button', { name: 'Enable Google Search' }))
    expect(catalogRequests.filter((agent) => agent === 'panthera')).toHaveLength(1)

    settingsPatch.resolve(settingsResponse('panthera', true))

    await waitFor(() => {
      expect(catalogRequests.filter((agent) => agent === 'panthera')).toHaveLength(2)
      expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('google_search')
    })
  })

  it('refreshes the current Felis catalog after changing its context window', async () => {
    appMocks.initialAgent = 'felis'
    const user = userEvent.setup()
    const settingsPatch = deferred<Response>()
    const catalogRequests: AgentKey[] = []
    let felisCatalogRequests = 0

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const agent = url.searchParams.get('agent') as AgentKey
          catalogRequests.push(agent)
          const refreshedContextWindow =
            agent === 'felis' && felisCatalogRequests++ > 0 ? 32768 : 16384
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor(agent, false, refreshedContextWindow)),
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

    await user.click(screen.getByRole('button', { name: 'Cortex' }))
    await waitFor(() => expect(catalogRequests).toContain('felis'))
    await waitFor(() => {
      expect(screen.getByTestId('active-agent')).toHaveTextContent('felis')
      expect(screen.getByTestId('catalog-context-window')).toHaveTextContent('16384')
    })

    const contextSelect = screen.getByRole('combobox', { name: 'Context window' })
    await user.selectOptions(contextSelect, '32768')
    expect(contextSelect).toHaveValue('32768')
    expect(catalogRequests.filter((agent) => agent === 'felis')).toHaveLength(1)

    settingsPatch.resolve(settingsResponse('felis', false, 32768))

    await waitFor(() => {
      expect(catalogRequests.filter((agent) => agent === 'felis')).toHaveLength(2)
      expect(screen.getByTestId('catalog-context-window')).toHaveTextContent('32768')
    })
  })

  it('refreshes the current catalog after toggling sandbox mode', async () => {
    appMocks.devModeActive = true
    const user = userEvent.setup()
    const catalogRequests: AgentKey[] = []
    let sandboxPatch: Record<string, unknown> | null = null

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const agent = url.searchParams.get('agent') as AgentKey
          catalogRequests.push(agent)
          return Promise.resolve(new Response(
            JSON.stringify(catalogFor(agent)),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ))
        }
        if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
          sandboxPatch = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(settingsResponse('panthera', false, 16384, true))
        }
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Cortex' }))
    await waitFor(() => expect(catalogRequests).toContain('panthera'))

    await user.click(screen.getByRole('checkbox', { name: 'Sandbox mode' }))

    await waitFor(() => {
      expect(sandboxPatch).toEqual({ ask_apex: { sandbox_mode: true } })
      expect(catalogRequests.filter((agent) => agent === 'panthera')).toHaveLength(2)
    })
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
