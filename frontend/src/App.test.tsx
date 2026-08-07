import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AgentKey, ToolCatalog } from './types/telemetry'

const appMocks = vi.hoisted(() => ({
  initialAgent: 'neofelis' as AgentKey,
  refreshAgentsStatus: vi.fn().mockResolvedValue(undefined),
  queryAgent: vi.fn().mockResolvedValue(undefined),
  clearCortexSession: vi.fn(),
  loadLocalModel: vi.fn().mockResolvedValue(true),
  unloadLocalModel: vi.fn().mockResolvedValue(true),
  verifyCloudAgent: vi.fn().mockResolvedValue(true),
  applyBootSettings: vi.fn(),
  markReminderAsRead: vi.fn().mockResolvedValue(undefined),
  createReminder: vi.fn().mockResolvedValue(undefined),
  activate: vi.fn(),
  requestOperation: vi.fn().mockResolvedValue('proceed'),
  refreshAll: vi.fn().mockResolvedValue(null),
  refreshConnector: vi.fn().mockResolvedValue(undefined),
  loadLatest: vi.fn().mockResolvedValue(undefined),
  triggerSynthesis: vi.fn().mockResolvedValue(undefined),
  generateFromSnapshot: vi.fn().mockResolvedValue(undefined),
  speak: vi.fn(),
}))

vi.mock('./components/ApexLogo', () => ({ ApexLogo: () => null }))
vi.mock('./components/CelestialBackground', () => ({ CelestialBackground: () => null }))
vi.mock('./components/BriefingDigest', () => ({ BriefingDigest: () => null }))
vi.mock('./components/CalendarEventList', () => ({ CalendarEventList: () => null }))
vi.mock('./components/FootballFixtureList', () => ({ FootballFixtureList: () => null }))
vi.mock('./components/MarketTickerCard', () => ({ MarketTickerCard: () => null }))
vi.mock('./components/PreflightDialog', () => ({ PreflightDialog: () => null }))
vi.mock('./components/ReminderListRow', () => ({ ReminderListRow: () => null }))
vi.mock('./components/ReminderQuickAdd', () => ({ ReminderQuickAdd: () => null }))
vi.mock('./components/TelemetryCard', () => ({ TelemetryCard: () => null }))
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
    onLocalContextWindowChange,
    onGoogleSearchChange,
    toolCatalog,
  }: {
    activeAgent: AgentKey
    onLocalContextWindowChange: (agent: AgentKey, contextWindow: number) => void
    onGoogleSearchChange: (enabled: boolean) => void
    toolCatalog: ToolCatalog | null
  }) => (
    <div>
      <output data-testid="active-agent">{activeAgent}</output>
      <output data-testid="provider-hosted-tools">
        {toolCatalog?.provider_hosted_tools.join(',') ?? ''}
      </output>
      <output data-testid="catalog-context-window">
        {toolCatalog?.context_window ?? ''}
      </output>
      {activeAgent === 'apodemus' || activeAgent === 'neotoma' ? (
        <button type="button" onClick={() => onLocalContextWindowChange(activeAgent, 32768)}>
          Increase Local Context
        </button>
      ) : (
        <button type="button" onClick={() => onGoogleSearchChange(true)}>
          Enable Google Search
        </button>
      )}
    </div>
  ),
}))

vi.mock('./hooks/useApexData', () => ({
  useApexData: () => ({
    activeReminders: [],
    createReminder: appMocks.createReminder,
    demoModeActive: false,
    devModeActive: false,
    askApexEnabled: true,
    marketEnabled: false,
    defaultAgent: appMocks.initialAgent,
    agentInitialSelection: {
      runtime: appMocks.initialAgent === 'apodemus' || appMocks.initialAgent === 'neotoma' ? 'local' : 'cloud',
      agent: appMocks.initialAgent,
      effort: 'focused',
    },
    briefingDefaultMode: 'panthera',
    voiceMode: 'automatic',
    markReminderAsRead: appMocks.markReminderAsRead,
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
      runtime: appMocks.initialAgent === 'apodemus' || appMocks.initialAgent === 'neotoma' ? 'local' : 'cloud',
      status: appMocks.initialAgent === 'apodemus' || appMocks.initialAgent === 'neotoma' ? 'available' : 'configured',
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
    snapshot: null,
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
    context_window: agent === 'apodemus' || agent === 'neotoma' ? contextWindow : null,
    reserved_response_tokens: agent === 'apodemus' || agent === 'neotoma' ? 512 : null,
  }
}

function settingsResponse(
  agent: AgentKey,
  googleSearchEnabled = false,
  contextWindow = 16384,
): Response {
  return new Response(JSON.stringify({
    schema_version: 13,
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
        runtime: agent === 'apodemus' || agent === 'neotoma' ? 'local' : 'cloud',
        cloud_agent: 'neofelis',
        effort: 'focused',
        local_agent: agent === 'apodemus' || agent === 'neotoma' ? agent : 'mus',
        local_context_windows: {
          apodemus: contextWindow,
          neotoma: 16384,
        },
        local_reasoning_modes: {
          sorex: 'none',
          mus: 'none',
          apodemus: 'none',
          neotoma: 'none',
        },
        neofelis_google_search_enabled: googleSearchEnabled,
        neofelis_google_maps_enabled: false,
        delphinus_x_search_enabled: false,
        orcinus_x_search_enabled: false,
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
    appMocks.initialAgent = 'neofelis'
    vi.restoreAllMocks()
  })

  it('refreshes the current Neofelis catalog after enabling Google Search', async () => {
    const user = userEvent.setup()
    const settingsPatch = deferred<Response>()
    const catalogRequests: AgentKey[] = []
    let neofelisCatalogRequests = 0

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const agent = url.searchParams.get('agent') as AgentKey
          catalogRequests.push(agent)
          const googleSearchEnabled =
            agent === 'neofelis' && neofelisCatalogRequests++ > 0
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
    await waitFor(() => expect(catalogRequests).toContain('neofelis'))
    await waitFor(() => expect(screen.getByTestId('active-agent')).toHaveTextContent('neofelis'))
    expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('')

    await user.click(screen.getByRole('button', { name: 'Enable Google Search' }))
    expect(catalogRequests.filter((agent) => agent === 'neofelis')).toHaveLength(1)

    settingsPatch.resolve(settingsResponse('neofelis', true))

    await waitFor(() => {
      expect(catalogRequests.filter((agent) => agent === 'neofelis')).toHaveLength(2)
      expect(screen.getByTestId('provider-hosted-tools')).toHaveTextContent('google_search')
    })
  })

  it('refreshes the current Apodemus catalog after changing its context window', async () => {
    appMocks.initialAgent = 'apodemus'
    const user = userEvent.setup()
    const settingsPatch = deferred<Response>()
    const catalogRequests: AgentKey[] = []
    let apodemusCatalogRequests = 0

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(String(input))
        if (url.pathname.endsWith('/cortex/tool-catalog')) {
          const agent = url.searchParams.get('agent') as AgentKey
          catalogRequests.push(agent)
          const refreshedContextWindow =
            agent === 'apodemus' && apodemusCatalogRequests++ > 0 ? 32768 : 16384
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
    await waitFor(() => expect(catalogRequests).toContain('apodemus'))
    await waitFor(() => {
      expect(screen.getByTestId('active-agent')).toHaveTextContent('apodemus')
      expect(screen.getByTestId('catalog-context-window')).toHaveTextContent('16384')
    })

    await user.click(screen.getByRole('button', { name: 'Increase Local Context' }))
    expect(catalogRequests.filter((agent) => agent === 'apodemus')).toHaveLength(1)

    settingsPatch.resolve(settingsResponse('apodemus', false, 32768))

    await waitFor(() => {
      expect(catalogRequests.filter((agent) => agent === 'apodemus')).toHaveLength(2)
      expect(screen.getByTestId('catalog-context-window')).toHaveTextContent('32768')
    })
  })
})
