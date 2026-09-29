import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState, type ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { ApexLogoProps } from './components/ApexLogo'
import type { AgentKey, ModelCatalogEntry, TelemetrySnapshot, ToolCatalog } from './types/telemetry'
import type { RuntimeSettings, SettingsResponse } from './types/settings'
import { BASE_SETTINGS, buildSettingsResponse } from './test/settingsFixtures'

const appMocks = vi.hoisted(() => ({
  initialAgent: 'apex' as AgentKey,
  initialModelId: 'deepseek/deepseek-v4-flash-0731',
  initialModelRuntime: 'cloud' as 'cloud' | 'local',
  localBriefingModel: null as ModelCatalogEntry | null,
  cortexLifecycleBusy: false,
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
  ApexLogo: ({ reminderPulseCount, status, activity, hasCollectedTelemetry }: Pick<ApexLogoProps, 'reminderPulseCount' | 'status' | 'activity' | 'hasCollectedTelemetry'>) => (
    <output data-testid="reminder-pulse-count" data-status={status} data-activity={activity ?? 'none'} data-collected={String(hasCollectedTelemetry ?? false)}>
      {reminderPulseCount ?? 0}
    </output>
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
vi.mock('./components/VoiceSignalGlyph', () => ({
  VoiceSignalGlyph: ({ isLocalModelLoading, loadingDisplayName, activity, isTelemetryCollecting }: { isLocalModelLoading: boolean; loadingDisplayName?: string | null; activity?: string | null; isTelemetryCollecting?: boolean }) => (
    <>
      {isLocalModelLoading ? <output data-testid="local-model-loading-label">{loadingDisplayName}</output> : null}
      <output data-testid="voice-activity" data-activity={activity ?? 'none'} data-telemetry-collecting={String(isTelemetryCollecting ?? false)}>{activity ?? 'none'}</output>
    </>
  ),
}))
vi.mock('./components/SettingsPanel', () => ({
  default: ({ onApplied }: { onApplied: unknown }) => {
    appMocks.settingsPanelApplied = onApplied
    return null
  },
}))
vi.mock('./components/SystemDiagnostics', () => ({
  SystemDiagnostics: ({ workspaceNavigation, onReturnToLaunch, onRefreshConnectors }: { workspaceNavigation?: ReactNode; onReturnToLaunch?: () => void; onRefreshConnectors?: () => void }) => (
    <>{workspaceNavigation}<button type="button" onClick={onReturnToLaunch}>APEX Launch</button><button type="button" onClick={onRefreshConnectors}>Refresh checks</button></>
  ),
}))
vi.mock('./components/CortexWorkspace', () => ({
  CortexWorkspace: ({
    activeAgent,
    devModeActive,
    sandboxMode,
    lifecycleBusy,
    onLocalContextWindowChange,
    onHostedToolChange,
    onSandboxModeChange,
    toolCatalog,
    actions,
    logoProps,
  }: {
    activeAgent: AgentKey
    devModeActive: boolean
    sandboxMode: boolean
    lifecycleBusy: boolean
    onLocalContextWindowChange: (contextWindow: number) => Promise<boolean>
    onHostedToolChange: (tool: 'google_search' | 'google_maps', enabled: boolean) => void
    onSandboxModeChange: (enabled: boolean) => void
    toolCatalog: ToolCatalog | null
    actions?: { pendingCount: number }
    logoProps?: Pick<ApexLogoProps, 'status' | 'hasCollectedTelemetry'>
  }) => {
    appMocks.cortexLifecycleBusy = lifecycleBusy
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
        {logoProps && <output data-testid="reminder-pulse-count" data-status={logoProps.status} data-collected={String(logoProps.hasCollectedTelemetry ?? false)} />}
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
        <output data-testid="cortex-lifecycle-busy">{String(lifecycleBusy)}</output>
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
    remindersLoadState: 'loaded' as const,
    createReminder: appMocks.createReminder,
    demoModeActive: appMocks.demoModeActive,
    devModeActive: appMocks.devModeActive,
    agentQueriesEnabled: true,
    marketEnabled: appMocks.marketEnabled,
    defaultAgent: 'apex' as AgentKey,
    agentInitialSelection: {
      runtime: appMocks.initialModelRuntime,
      agent: 'apex' as AgentKey,
      modelId: appMocks.initialModelId,
      effort: 'low',
    },
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
        reasoning_options: ['low', 'medium', 'high'],
        default_reasoning: 'low',
        hosted_capabilities: [],
      }],
    },
    modelCatalog: appMocks.noModels ? [] : [
      {
        model_id: 'deepseek/deepseek-v4-flash-0731',
        display_name: 'DeepSeek V4 Flash',
        provider: 'openrouter',
        runtime: 'cloud',
        stability: 'stable',
        reasoning_options: ['low', 'medium', 'high'],
        default_reasoning: 'low',
        hosted_capabilities: [],
      },
      ...(appMocks.localBriefingModel ? [appMocks.localBriefingModel] : []),
    ],
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

function briefingSettingsResponse(
  patchBody: unknown,
  adjust?: (settings: RuntimeSettings) => void,
): Response {
  const patch = (patchBody as { ask_apex?: Record<string, unknown> }).ask_apex ?? {}
  const settings = structuredClone(BASE_SETTINGS)
  const selectedModel = patch.selected_model
  if (typeof selectedModel === 'string') settings.ask_apex.selected_model = selectedModel
  if (patch.cloud && typeof patch.cloud === 'object') {
    Object.assign(settings.ask_apex.cloud, patch.cloud)
  }
  if (patch.local && typeof patch.local === 'object') {
    Object.assign(settings.ask_apex.local, patch.local)
  }
  adjust?.(settings)
  return new Response(JSON.stringify(buildSettingsResponse(settings)), {
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
  const nav = screen.getByRole('navigation', { name: 'Workspace' })
  await user.click(within(nav).getByRole('button', { name }))
}

function renderOverviewApp(): ReturnType<typeof render> {
  const result = render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Overview' }))
  return result
}

function usableTelemetrySnapshot(): TelemetrySnapshot {
  const collectedAt = new Date().toISOString()
  return {
    snapshot_id: 'test-snapshot',
    collected_at: collectedAt,
    modules: {
      weather: {
        name: 'weather', status: 'healthy', freshness: 'live', reason_code: 'ok',
        observed_at: collectedAt, display_text: 'Clear', data: { temp_f: 72, condition: 'mainly clear' },
      },
    },
    sync_health_score: 100,
    connector_health: [],
    failed_connectors: [],
  }
}

async function collectOverview(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Collect Telemetry' })).not.toBeInTheDocument())
}

async function selectBriefingEffort(user: ReturnType<typeof userEvent.setup>, effort: string): Promise<void> {
  const dialog = screen.getByRole('dialog', { name: 'Set up your briefing' })
  await user.click(within(dialog).getByRole('button', { name: /^Select effort/ }))
  const effortChoices = within(dialog).getByRole('group', { name: 'Reasoning effort choices' })
  await user.click(within(effortChoices).getByRole('button', { name: effort }))
}

describe('App catalog-affecting settings', () => {
  afterEach(() => {
    appMocks.initialAgent = 'apex'
    appMocks.initialModelId = 'deepseek/deepseek-v4-flash-0731'
    appMocks.initialModelRuntime = 'cloud'
    appMocks.localBriefingModel = null
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

    renderOverviewApp()

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

  it('uses the shared cloud reasoning effort for Briefing follow-ups and disables preflight in Reports', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(catalogFor('apex')), { status: 200 }))))
    appMocks.toolPreflight.mockClear()

    renderOverviewApp()
    const baseline = structuredClone(BASE_SETTINGS)
    const withHighCloudEffort = structuredClone(BASE_SETTINGS)
    withHighCloudEffort.ask_apex.cloud.effort = 'high'
    await applySavedSettings(buildSettingsResponse(withHighCloudEffort), baseline)
    await waitFor(() => expect(appMocks.toolPreflight.mock.lastCall?.[0]).toMatchObject({
      modelId: 'deepseek/deepseek-v4-flash-0731',
      effort: 'high',
      contextWindow: null,
      localReasoningMode: null,
    }))

    await selectWorkspace(user, 'Reports')
    await waitFor(() => expect(appMocks.toolPreflight.mock.lastCall?.[0]).toMatchObject({
      effort: 'high',
      enabled: false,
    }))
  })

  it('uses the shared local context window and reasoning mode for Briefing follow-ups', async () => {
    appMocks.localBriefingModel = {
      model_id: 'qwen3:1.7b',
      display_name: 'Qwen 3 1.7B',
      provider: 'ollama',
      runtime: 'local',
      stability: 'stable',
      reasoning_modes: ['none', 'focused'],
      context_options: [16384, 32768],
      hosted_capabilities: [],
    }
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(catalogFor('apex')), { status: 200 }))))
    appMocks.toolPreflight.mockClear()

    renderOverviewApp()
    const localSettings = structuredClone(BASE_SETTINGS)
    localSettings.ask_apex.selected_model = 'qwen3:1.7b'
    localSettings.ask_apex.local.last_model = 'qwen3:1.7b'
    localSettings.ask_apex.local.context_window = 32768
    localSettings.ask_apex.local.reasoning_mode = 'focused'
    await applySavedSettings(buildSettingsResponse(localSettings), structuredClone(BASE_SETTINGS))

    await waitFor(() => expect(appMocks.toolPreflight.mock.lastCall?.[0]).toMatchObject({
      modelId: 'qwen3:1.7b',
      effort: null,
      contextWindow: 32768,
      localReasoningMode: 'focused',
    }))
  })

  it('switches peer workspaces from visible header tabs without a Standby peer', async () => {
    const user = userEvent.setup()
    renderOverviewApp()

    const nav = screen.getByRole('navigation', { name: 'Workspace' })
    const tabs = within(nav).getAllByRole('button')
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Overview', 'Briefing', 'Cortex', 'Reports'])
    expect(within(nav).getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('button', { name: 'Briefing' })).not.toHaveAttribute('aria-current')

    await selectWorkspace(user, 'Reports')
    expect(within(nav).getByRole('button', { name: 'Reports' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument()

    await selectWorkspace(user, 'Briefing')
    expect(within(nav).getByRole('button', { name: 'Briefing' })).toHaveAttribute('aria-current', 'page')
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

    renderOverviewApp()

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

    renderOverviewApp()

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

  it('shows loading only while Market participates in telemetry refresh', async () => {
    appMocks.marketEnabled = true
    appMocks.telemetryRefreshingAll = true
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })
    const user = userEvent.setup()
    const { rerender } = renderOverviewApp()
    await collectOverview(user)
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
    const { rerender } = renderOverviewApp()
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
  it('keeps Open-Meteo, GeoNames, licence, and adaptation credit visible in the weather header', async () => {
    appMocks.weatherSnapshot = {
      modules: {
        weather: {
          status: 'healthy',
          data: { temp_f: 72, condition: 'mainly clear' },
          display_text: 'Current temperature is 72 degrees with mainly clear.',
        },
      },
    }
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })
    const user = userEvent.setup()
    renderOverviewApp()
    await collectOverview(user)

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
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })

    renderOverviewApp()
    await collectOverview(user)

    expect(screen.getByTestId('reminder-pulse-count')).toHaveTextContent('0')
    await user.click(screen.getByRole('button', { name: 'Add reminder' }))

    await waitFor(() => expect(screen.getByTestId('reminder-pulse-count')).toHaveTextContent('1'))
    expect(appMocks.createReminder).toHaveBeenCalledWith('Call the dentist')
  })

  it('opens completed reminders from the panel header without renaming the panel', async () => {
    const user = userEvent.setup()
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })
    renderOverviewApp()
    await collectOverview(user)

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
    appMocks.loadLatest.mockReset().mockResolvedValue(null)
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubAppFetch(events: string[], options: { reusable?: boolean } = {}): void {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/telemetry/reuse')) {
        return Promise.resolve(new Response(JSON.stringify({ reusable: options.reusable ?? false }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (url.pathname.endsWith('/voice/cue')) {
        const body = JSON.parse(String(init?.body)) as { cue: string }
        events.push(`cue:${body.cue}`)
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

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => {
      expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_ready'])
    })
  })

  it('skips the collecting cue when the refresh reuses a fresh snapshot but still announces the result', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    stubAppFetch(events, { reusable: true })
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_ready']))
  })

  it('stays silent about collecting when the reuse check cannot be confirmed', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/telemetry/reuse')) return Promise.reject(new Error('offline'))
      if (url.pathname.endsWith('/voice/cue')) events.push(`cue:${(JSON.parse(String(init?.body)) as { cue: string }).cue}`)
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_ready']))
  })

  it('does not race a cached snapshot load against the explicit refresh', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    appMocks.loadLatest.mockResolvedValue(createTelemetrySnapshot())
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot() }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_ready']))
    expect(appMocks.loadLatest).not.toHaveBeenCalled()
  })

  it('keeps the center error state when the first refresh fails despite cached usable telemetry', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    appMocks.telemetrySnapshot = createTelemetrySnapshot()
    appMocks.loadLatest.mockResolvedValue(createTelemetrySnapshot())
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'failure', snapshot: null, error: 'network down' }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_refresh_failed']))
    expect(await screen.findByRole('alert')).toHaveTextContent('network down')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
    expect(screen.queryByTestId('weather-compact-value')).not.toBeInTheDocument()
    expect(appMocks.loadLatest).not.toHaveBeenCalled()
  })

  it('treats a stale module in a successful refresh as no data', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    const freshAt = new Date().toISOString()
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return {
        kind: 'success',
        snapshot: createTelemetrySnapshot(freshAt, {
          weather: {
            name: 'weather',
            status: 'healthy',
            freshness: 'stale',
            reason_code: 'stale',
            observed_at: freshAt,
            display_text: 'Old clear conditions',
            data: {},
          },
        }),
      }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_no_fresh_telemetry']))
    expect(await screen.findByText('No telemetry sources are available yet.')).toBeInTheDocument()
  })

  it('rejects an old cached module even when its freshness label is not stale', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    const oldAt = new Date(Date.now() - 6 * 60 * 1000).toISOString()
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockResolvedValue({
      kind: 'success',
      snapshot: createTelemetrySnapshot(oldAt, {
        weather: {
          name: 'weather',
          status: 'healthy',
          freshness: 'fresh_cache',
          reason_code: 'cached',
          observed_at: oldAt,
          display_text: 'Old clear conditions',
          data: {},
        },
      }),
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(events).toEqual(['cue:activation_loading', 'cue:activation_no_fresh_telemetry']))
    expect(await screen.findByText('No telemetry sources are available yet.')).toBeInTheDocument()
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

    const firstRender = renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
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
    renderOverviewApp()
    await secondUser.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
    await waitFor(() => expect(events).toEqual(['cue:activation_loading']))
  })

  it('uses the no-data cue when no telemetry modules are usable', async () => {
    const user = userEvent.setup()
    const events: string[] = []
    appMocks.activated = false
    stubAppFetch(events)
    appMocks.refreshAllWithOutcome.mockImplementation(async () => {
      events.push('refresh')
      return { kind: 'success', snapshot: createTelemetrySnapshot(new Date().toISOString(), {}) }
    })

    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => {
      expect(events).toEqual(['refresh', 'cue:activation_loading', 'cue:activation_no_fresh_telemetry'])
    })
  })

})

describe('App Overview and Briefing states', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.noModels = false
    appMocks.weatherSnapshot = null
    appMocks.telemetrySnapshot = null
    appMocks.deactivate.mockClear()
    appMocks.activate.mockClear()
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
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

  it('opens on Launch and offers Collect Telemetry after navigating to Overview', async () => {
    appMocks.activated = false
    appMocks.loadLatest.mockClear()
    appMocks.requestOperation.mockClear()
    stubHomeFetch([])
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('region', { name: 'Launch' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open settings' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Collect Telemetry' })).not.toBeInTheDocument()
    expect(appMocks.loadLatest).not.toHaveBeenCalled()
    await selectWorkspace(user, 'Overview')

    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Open Briefing setup' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Agent command rail' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('shares standby logo state across workspaces and leaves it uncollected after failure', async () => {
    appMocks.activated = false
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'failure', snapshot: null, error: 'offline' })
    stubHomeFetch([])
    const user = userEvent.setup()
    render(<App />)

    const expectStandbyLogo = (): void => {
      const logos = screen.getAllByTestId('reminder-pulse-count')
      expect(logos.length).toBeGreaterThan(0)
      for (const logo of logos) {
        expect(logo).toHaveAttribute('data-status', 'idle')
        expect(logo).toHaveAttribute('data-collected', 'false')
      }
    }

    expectStandbyLogo()
    await selectWorkspace(user, 'Overview')
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument())
    expectStandbyLogo()

    await selectWorkspace(user, 'Briefing')
    expectStandbyLogo()
    await selectWorkspace(user, 'Cortex')
    expectStandbyLogo()
  })

  it('uses the collected logo state across workspaces after a usable snapshot', async () => {
    appMocks.activated = false
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })
    stubHomeFetch([])
    const user = userEvent.setup()
    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => {
      for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
        expect(logo).toHaveAttribute('data-status', 'success')
        expect(logo).toHaveAttribute('data-collected', 'true')
      }
    })

    await selectWorkspace(user, 'Briefing')
    for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
      expect(logo).toHaveAttribute('data-status', 'success')
      expect(logo).toHaveAttribute('data-collected', 'true')
    }
  })

  it('keeps the telemetry standby state after a no-data collection', async () => {
    appMocks.activated = false
    appMocks.refreshAllWithOutcome.mockResolvedValue({
      kind: 'success',
      snapshot: { ...usableTelemetrySnapshot(), modules: {} },
    })
    stubHomeFetch([])
    const user = userEvent.setup()
    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument())
    for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
      expect(logo).toHaveAttribute('data-status', 'idle')
      expect(logo).toHaveAttribute('data-collected', 'false')
    }
  })

  it('latches a usable snapshot supplied outside Overview collection', async () => {
    appMocks.activated = false
    appMocks.telemetrySnapshot = usableTelemetrySnapshot()
    stubHomeFetch([])
    const user = userEvent.setup()
    const { rerender } = render(<App />)

    await waitFor(() => {
      for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
        expect(logo).toHaveAttribute('data-status', 'success')
        expect(logo).toHaveAttribute('data-collected', 'true')
      }
    })

    appMocks.telemetrySnapshot = null
    rerender(<App />)
    for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
      expect(logo).toHaveAttribute('data-status', 'success')
      expect(logo).toHaveAttribute('data-collected', 'true')
    }

    await selectWorkspace(user, 'Briefing')
    for (const logo of screen.getAllByTestId('reminder-pulse-count')) {
      expect(logo).toHaveAttribute('data-status', 'success')
      expect(logo).toHaveAttribute('data-collected', 'true')
    }
  })

  it('shows telemetry in Overview without a model, composer, or briefing controls', async () => {
    appMocks.noModels = true
    appMocks.refreshAllWithOutcome.mockResolvedValue({
      kind: 'success',
      snapshot: {
        snapshot_id: 'overview-snapshot',
        collected_at: new Date().toISOString(),
        modules: { weather: { name: 'weather', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: new Date().toISOString(), data: { temp_f: 72 }, display_text: 'Current temperature is 72 degrees.' } },
        sync_health_score: 100,
        connector_health: [],
        failed_connectors: [],
      },
    })
    stubHomeFetch([])
    const user = userEvent.setup()
    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByTestId('weather-compact-value')).not.toBeEmptyDOMElement()
    expect(screen.getByRole('button', { name: 'Refresh Reminders' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Briefing controls' })).not.toBeInTheDocument()
  })

  it('keeps the ready Overview grid visible after a later refresh failure', async () => {
    appMocks.refreshAllWithOutcome.mockResolvedValue({ kind: 'success', snapshot: usableTelemetrySnapshot() })
    appMocks.refreshAll.mockResolvedValue({ kind: 'failure', snapshot: null, error: 'network down' })
    stubHomeFetch([])
    const user = userEvent.setup()
    renderOverviewApp()
    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))

    expect(screen.getByRole('button', { name: 'Refresh Reminders' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh All' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh All' }))

    expect(appMocks.refreshAll).toHaveBeenCalledWith({ force: false })
    expect(screen.getByRole('button', { name: 'Refresh Reminders' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry Telemetry' })).not.toBeInTheDocument()
  })

  it('switches workspaces and returns to Launch without generating', async () => {
    const user = userEvent.setup()
    const posts: string[] = []
    stubHomeFetch(posts)
    renderOverviewApp()

    await selectWorkspace(user, 'Briefing')
    expect(screen.getByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Standby' })).not.toBeInTheDocument()

    await selectWorkspace(user, 'Overview')
    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
    expect(appMocks.requestOperation).not.toHaveBeenCalledWith('activate')

    await user.click(screen.getByRole('button', { name: 'APEX Launch' }))
    expect(screen.getByRole('region', { name: 'Launch' })).toBeInTheDocument()
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
  })

  it('opens Briefing from Overview without activation or generating a briefing', async () => {
    appMocks.activated = false
    appMocks.activate.mockClear()
    const user = userEvent.setup()
    const posts: string[] = []
    stubHomeFetch(posts)
    renderOverviewApp()

    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()

    await selectWorkspace(user, 'Briefing')
    expect(appMocks.activate).not.toHaveBeenCalled()
    expect(await screen.findByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Set up your briefing' })).not.toBeInTheDocument()
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
  })

  it('collects telemetry from Briefing in place and reveals the sections when the snapshot is usable', async () => {
    appMocks.activated = false
    appMocks.activate.mockClear()
    appMocks.requestOperation.mockClear()
    const refresh = deferred<{
      kind: 'success'
      snapshot: TelemetrySnapshot
    }>()
    appMocks.refreshAllWithOutcome.mockReturnValue(refresh.promise)
    const user = userEvent.setup()
    stubHomeFetch([])
    renderOverviewApp()

    await selectWorkspace(user, 'Briefing')
    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    await user.click(within(rail).getByRole('button', { name: 'Collect Telemetry' }))

    expect(appMocks.requestOperation).toHaveBeenCalledWith('activate')
    expect(appMocks.activate).toHaveBeenCalledOnce()
    expect(await within(rail).findByText('Collecting telemetry…')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument()

    await act(async () => refresh.resolve({ kind: 'success', snapshot: usableTelemetrySnapshot() }))

    expect(await within(rail).findByTestId('weather-compact-value')).toBeInTheDocument()
    expect(within(rail).queryByRole('button', { name: 'Collect Telemetry' })).not.toBeInTheDocument()
    expect(within(rail).getByTestId('market-loading-state')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
  })

  it('refreshes saved sessions whenever returning to Briefing from Cortex', async () => {
    let sessionListReads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/briefing-sessions')) {
        sessionListReads += 1
        return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.pathname.endsWith('/cortex/conversations')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const user = userEvent.setup()
    renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await waitFor(() => expect(sessionListReads).toBeGreaterThanOrEqual(2))
    const readsOnBriefingEntry = sessionListReads

    await selectWorkspace(user, 'Cortex')
    await selectWorkspace(user, 'Briefing')

    await waitFor(() => expect(sessionListReads).toBeGreaterThan(readsOnBriefingEntry))
  })

  it('opens Briefing setup from the Briefing tab without activation, even without a model', async () => {
    appMocks.activated = false
    appMocks.noModels = true
    appMocks.activate.mockClear()
    const user = userEvent.setup()
    const posts: string[] = []
    stubHomeFetch(posts)
    renderOverviewApp()

    await selectWorkspace(user, 'Briefing')
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))

    expect(await screen.findByRole('dialog', { name: 'Set up your briefing' })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
    expect(appMocks.requestOperation).not.toHaveBeenCalledWith('activate')
    expect(appMocks.activate).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Generate Daily' })).toBeDisabled()
    expect(posts.filter((path) => path.endsWith('/briefing-sessions'))).toHaveLength(0)
  })

  it('does not collect telemetry from Enter while on inactive Briefing', async () => {
    appMocks.activated = false
    appMocks.activate.mockClear()
    appMocks.requestOperation.mockClear()
    const user = userEvent.setup()
    stubHomeFetch([])
    renderOverviewApp()

    await selectWorkspace(user, 'Briefing')
    await user.keyboard('{Enter}')

    expect(appMocks.activate).not.toHaveBeenCalled()
    expect(appMocks.requestOperation).not.toHaveBeenCalledWith('activate')
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Briefing controls' })).toBeInTheDocument()
  })

  it('does not collect telemetry from the global Enter key in Overview', async () => {
    appMocks.activated = false
    appMocks.activate.mockClear()
    appMocks.requestOperation.mockClear()
    const user = userEvent.setup()
    stubHomeFetch([])
    renderOverviewApp()

    await user.keyboard('{Enter}')

    expect(appMocks.activate).not.toHaveBeenCalled()
    expect(appMocks.requestOperation).not.toHaveBeenCalledWith('activate')
    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeInTheDocument()
  })

  it('activates Overview from Collect Telemetry on Standby', async () => {
    appMocks.activated = false
    const user = userEvent.setup()
    stubHomeFetch([])
    renderOverviewApp()

    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
    expect(await screen.findByRole('region', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument()
  })
})

describe('App active local briefing lifecycle', () => {
  afterEach(() => {
    appMocks.initialModelId = 'deepseek/deepseek-v4-flash-0731'
    appMocks.initialModelRuntime = 'cloud'
    appMocks.localBriefingModel = null
    appMocks.cortexLifecycleBusy = false
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not treat an active local briefing as model loading while keeping lifecycle controls busy', async () => {
    appMocks.initialModelId = 'qwen3:1.7b'
    appMocks.initialModelRuntime = 'local'
    appMocks.localBriefingModel = {
      model_id: 'qwen3:1.7b',
      display_name: 'Qwen 3 1.7B',
      provider: 'ollama',
      runtime: 'local',
      stability: 'stable',
      hosted_capabilities: [],
    }
    const activeSummary = {
      id: '00000000-0000-4000-8000-000000000081',
      profile_id: 'daily',
      model_id: 'qwen3:1.7b',
      conversation_id: '00000000-0000-4000-8000-000000000082',
      run_id: '00000000-0000-4000-8000-000000000083',
      run_status: 'running',
      created_at: '2026-09-26T10:00:00Z',
      presented_at: null,
    }
    const activeDetail = deferred<Response>()
    let activeDetailBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/briefing-profiles')) {
        return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.pathname.endsWith('/briefing-sessions')) {
        return new Response(JSON.stringify([activeSummary]), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.pathname.endsWith(`/briefing-sessions/${activeSummary.id}`)) {
        return activeDetailBody === null
          ? activeDetail.promise
          : new Response(JSON.stringify(activeDetailBody), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    const user = userEvent.setup()
    renderOverviewApp()
    expect(await screen.findByTestId('voice-activity')).toHaveAttribute('data-activity', 'preparing')
    await act(async () => {
      activeDetailBody = {
        id: activeSummary.id,
        conversation_id: activeSummary.conversation_id,
        opening_message_id: '00000000-0000-4000-8000-000000000084',
        run_id: activeSummary.run_id,
        run_status: 'running',
        run_error_code: null,
        configuration: {
          profile: { id: 'daily', label: 'Daily', purpose: 'Current information.', definition_version: 1 },
          model: { model_id: activeSummary.model_id, provider: 'ollama', runtime: 'local', reasoning: null, context_window: null, local_reasoning_mode: null },
          origin: 'hud', execution_kind: 'model',
        },
        artifact: null,
        evidence_count: 0,
        evidence_ids: [],
        created_at: activeSummary.created_at,
        presented_at: null,
        speech_status: 'not_requested',
        active_stage: { stage: 'synthesizing', state: 'started' },
      }
      activeDetail.resolve(new Response(JSON.stringify(activeDetailBody), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    await waitFor(() => expect(screen.getByTestId('voice-activity')).toHaveAttribute('data-activity', 'synthesizing'))
    await waitFor(() => expect(screen.queryByTestId('local-model-loading-label')).not.toBeInTheDocument())

    await selectWorkspace(user, 'Cortex')
    expect(screen.getByTestId('cortex-lifecycle-busy')).toHaveTextContent('true')
    expect(appMocks.cortexLifecycleBusy).toBe(true)
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

  it('opens setup from Standby, saves selected model settings before admission, and preserves the conversation draft', async () => {
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
        model: { model_id: sessionSummary.model_id, provider: 'openrouter', runtime: 'cloud', reasoning: 'high', context_window: 16384, local_reasoning_mode: null },
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
    let settingsPatchBody: Record<string, unknown> | null = null
    const eventOrder: string[] = []
    const spokenCues: string[] = []
    let admissions = 0
    let detailReads = 0
    let presentationWrites = 0
    let cancellationWrites = 0
    let speechReads = 0
    let speechPrepares = 0
    let speechPlays = 0
    let speechStatus: 'not_requested' | 'preparing' | 'playing' | 'ready' = 'not_requested'
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
    appMocks.requestOperation.mockClear().mockImplementation(async (operation) => {
      eventOrder.push(`preflight:${operation}`)
      return 'proceed'
    })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      const path = url.pathname
      if (path.endsWith('/settings') && init?.method === 'PATCH') {
        settingsPatchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        eventOrder.push('settings-patch')
        return briefingSettingsResponse(settingsPatchBody)
      }
      if (path.endsWith('/voice/cue')) {
        spokenCues.push((JSON.parse(String(init?.body)) as { cue: string }).cue)
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/briefing-sessions') && init?.method === 'POST') {
        admissions += 1
        admissionBody = JSON.parse(String(init.body)) as Record<string, unknown>
        eventOrder.push('session-post')
        return new Response(JSON.stringify(sessionSummary), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/briefing-sessions') && init?.method !== 'POST') {
        const summaries = admissionBody ? [{ ...sessionSummary, run_status: runStatus }] : []
        return new Response(JSON.stringify(summaries), { status: 200, headers: { 'Content-Type': 'application/json' } })
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

    const app = renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const setup = await screen.findByRole('dialog', { name: 'Set up your briefing' })
    expect(admissions).toBe(0)
    expect(settingsPatchBody).toBeNull()
    await selectBriefingEffort(user, 'High')
    await user.click(within(setup).getByRole('button', { name: 'Generate Daily' }))

    await waitFor(() => expect(admissionBody).not.toBeNull())
    expect(appMocks.requestOperation).toHaveBeenCalledWith('generate_briefing_session', expect.objectContaining({
      model_id: 'deepseek/deepseek-v4-flash-0731',
      involves_cloud: true,
    }))
    expect(settingsPatchBody).toEqual({ ask_apex: {
      selected_model: 'deepseek/deepseek-v4-flash-0731',
      cloud: { last_model: 'deepseek/deepseek-v4-flash-0731', effort: 'high' },
    } })
    expect(admissionBody).toMatchObject({ profile_id: 'daily', model_id: 'deepseek/deepseek-v4-flash-0731', reasoning: 'high' })
    expect(eventOrder.indexOf('preflight:generate_briefing_session')).toBeLessThan(eventOrder.indexOf('settings-patch'))
    expect(eventOrder.indexOf('settings-patch')).toBeLessThan(eventOrder.indexOf('session-post'))
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

    appMocks.telemetryRefreshingAll = true
    app.rerender(<App />)
    await waitFor(() => expect(screen.getByTestId('voice-activity')).toHaveAttribute('data-telemetry-collecting', 'true'))
    expect(screen.getByTestId('voice-activity')).toHaveAttribute('data-activity', 'briefing_ready')
    expect(screen.getByRole('main').style.getPropertyValue('--atmosphere-glow-color')).toBe('57, 255, 136')
    appMocks.telemetryRefreshingAll = false
    app.rerender(<App />)
    await waitFor(() => expect(screen.getByRole('main').style.getPropertyValue('--atmosphere-glow-color')).toBe('15, 77, 184'))

    await user.click(prepareSpeech)
    await waitFor(() => expect(speechPrepares).toBe(1))
    await waitFor(() => expect(screen.getByTestId('voice-activity')).toHaveAttribute('data-activity', 'speech_preparing'))
    expect(speechPlays).toBe(0)
    speechStatus = 'playing'
    await waitFor(() => expect(screen.getByTestId('voice-activity')).toHaveAttribute('data-activity', 'speech_playing'), { timeout: 2500 })
    await waitFor(() => expect(presentationWrites).toBe(1))
    expect(admissions).toBe(1)
    const composer = await screen.findByRole('textbox')
    await user.type(composer, 'What about traffic?')
    await selectWorkspace(user, 'Reports')
    await selectWorkspace(user, 'Overview')
    expect(screen.queryByTestId('briefing-artifact')).not.toBeInTheDocument()
    await selectWorkspace(user, 'Briefing')

    expect(await screen.findByTestId('briefing-artifact')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('What about traffic?')
    expect(admissions).toBe(1)
    expect(presentationWrites).toBe(1)
    expect(cancellationWrites).toBe(0)
    expect(spokenCues).toEqual(['briefing_generating', 'briefing_ready'])
  }, 10000)
})

describe('App briefing setup failure ordering', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.demoModeActive = false
    appMocks.noModels = false
    appMocks.localBriefingModel = null
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not admit a session when saving briefing settings fails and keeps the draft open', async () => {
    let posts = 0
    let patches = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
        patches += 1
        return new Response(JSON.stringify({ detail: 'settings denied' }), { status: 503, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.pathname.endsWith('/briefing-sessions') && init?.method === 'POST') {
        posts += 1
      }
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const user = userEvent.setup()
    renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    await selectBriefingEffort(user, 'High')
    await user.click(screen.getByRole('button', { name: 'Generate Daily' }))

    const dialog = await screen.findByRole('dialog', { name: 'Set up your briefing' })
    expect(screen.getByRole('alert')).toHaveTextContent('settings denied')
    expect(screen.getByRole('button', { name: /^Select effort/ })).toHaveTextContent('High')
    expect(patches).toBe(1)
    expect(posts).toBe(0)
    expect(dialog).toBeInTheDocument()
  })

  it('keeps saved settings after session admission fails and reopens the draft with the error', async () => {
    let posts = 0
    let patches = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
        patches += 1
        return briefingSettingsResponse(JSON.parse(String(init.body)))
      }
      if (url.pathname.endsWith('/briefing-sessions') && init?.method === 'POST') {
        posts += 1
        return new Response(JSON.stringify({ detail: 'admission denied' }), { status: 503, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const user = userEvent.setup()
    renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    await selectBriefingEffort(user, 'High')
    await user.click(screen.getByRole('button', { name: 'Generate Daily' }))

    await screen.findByRole('alert')
    expect(screen.getByRole('alert')).toHaveTextContent('admission denied')
    expect(posts).toBe(1)
    expect(patches).toBe(1)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    expect(screen.getByRole('button', { name: /^Select effort/ })).toHaveTextContent('High')
    expect(patches).toBe(1)
  })
})

describe('App Repeat last briefing', () => {
  afterEach(() => {
    appMocks.activated = true
    appMocks.demoModeActive = false
    appMocks.noModels = false
    appMocks.localBriefingModel = null
    appMocks.requestOperation.mockReset().mockResolvedValue('proceed')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('repeats the newest failed CLI session using its saved profile and reasoning, regardless of displayed selection', async () => {
    const olderId = '00000000-0000-4000-8000-000000000101'
    const latestId = '00000000-0000-4000-8000-000000000102'
    const newId = '00000000-0000-4000-8000-000000000103'
    const conversationId = '00000000-0000-4000-8000-000000000104'
    const olderConversationId = '00000000-0000-4000-8000-000000000105'
    const newConversationId = '00000000-0000-4000-8000-000000000106'
    const makeSummary = (id: string, profileId: string, runStatus: string, createdAt: string) => ({
      id,
      profile_id: profileId,
      model_id: 'deepseek/deepseek-v4-flash-0731',
      conversation_id: id === olderId ? olderConversationId : id === newId ? newConversationId : conversationId,
      run_id: `run-${id.slice(-3)}`,
      run_status: runStatus,
      created_at: createdAt,
      presented_at: null,
    })
    const olderSummary = makeSummary(olderId, 'daily', 'completed', '2026-09-25T10:00:00Z')
    const latestSummary = makeSummary(latestId, 'catch_up', 'failed', '2026-09-26T10:00:00Z')
    const newSummary = makeSummary(newId, 'catch_up', 'running', '2026-09-27T10:00:00Z')
    const makeDetail = (summary: typeof latestSummary, runStatus: string) => ({
      id: summary.id,
      conversation_id: summary.conversation_id,
      opening_message_id: '00000000-0000-4000-8000-000000000105',
      run_id: summary.run_id,
      run_status: runStatus,
      run_error_code: runStatus === 'failed' ? 'provider_error' : null,
      configuration: {
        profile: {
          id: summary.profile_id,
          label: summary.profile_id === 'catch_up' ? 'Catch Up' : 'Daily',
          purpose: 'A saved briefing profile.',
          definition_version: 2,
        },
        model: {
          model_id: summary.model_id,
          provider: 'openrouter',
          runtime: 'cloud',
          reasoning: 'high',
          context_window: null,
          local_reasoning_mode: null,
        },
        origin: summary.id === latestId ? 'cli' : 'hud',
        execution_kind: 'model',
      },
      artifact: null,
      evidence_count: 0,
      evidence_ids: [],
      created_at: summary.created_at,
      presented_at: null,
      speech_status: 'not_requested',
    })
    const profiles = [
      { id: 'daily', label: 'Daily', purpose: 'Current information.', investigation_required: false, available: true, unavailable_reason: null },
      { id: 'catch_up', label: 'Catch Up', purpose: 'What changed.', investigation_required: false, available: true, unavailable_reason: null },
      { id: 'deep', label: 'Deep', purpose: 'Investigate.', investigation_required: true, available: true, unavailable_reason: null },
    ]
    let admissionBody: Record<string, unknown> | null = null
    let settingsPatchBody: Record<string, unknown> | null = null
    const conversationSummary = (id: string) => ({
      id,
      title: 'Briefing conversation',
      archived_at: null,
      agent: 'apex',
      selected_tool_names: [],
      tool_profile_id: null,
      updated_at: '2026-09-27T10:00:00Z',
    })
    const conversationDetail = (id: string) => ({
      ...conversationSummary(id),
      active_leaf_message_id: null,
      messages: [],
    })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      const path = url.pathname
      if (path.endsWith('/briefing-profiles')) return new Response(JSON.stringify(profiles), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/briefing-sessions') && init?.method === 'POST') {
        admissionBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify(newSummary), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/briefing-sessions')) {
        const list = url.searchParams.get('limit') === '1' ? [latestSummary] : admissionBody ? [newSummary, latestSummary, olderSummary] : [latestSummary, olderSummary]
        return new Response(JSON.stringify(list), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/settings') && init?.method === 'PATCH') {
        settingsPatchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return briefingSettingsResponse(settingsPatchBody)
      }
      if (path.endsWith(`/briefing-sessions/${latestId}`)) return new Response(JSON.stringify(makeDetail(latestSummary, 'failed')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/briefing-sessions/${olderId}`)) return new Response(JSON.stringify(makeDetail(olderSummary, 'completed')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/briefing-sessions/${newId}`)) return new Response(JSON.stringify(makeDetail(newSummary, 'running')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/cortex/conversations')) {
        const ids = admissionBody ? [conversationId, olderConversationId, newConversationId] : [conversationId, olderConversationId]
        return new Response(JSON.stringify(ids.map(conversationSummary)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/cortex/conversations/${conversationId}`)) return new Response(JSON.stringify(conversationDetail(conversationId)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/cortex/conversations/${olderConversationId}`)) return new Response(JSON.stringify(conversationDetail(olderConversationId)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/cortex/conversations/${newConversationId}`)) return new Response(JSON.stringify(conversationDetail(newConversationId)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/cortex/tool-catalog')) return new Response(JSON.stringify(catalogFor('apex')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    const user = userEvent.setup()
    renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Repeat last briefing' })).toBeEnabled())
    expect(screen.getByText(/Catch Up · DeepSeek V4 Flash · failed/)).toBeInTheDocument()
    const savedSessions = await screen.findByRole('navigation', { name: 'Saved briefing sessions' })
    await user.click(within(savedSessions).getByRole('button', { name: /Daily/ }))
    expect(screen.getByText(/Catch Up · DeepSeek V4 Flash · failed/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Repeat last briefing' }))

    await waitFor(() => expect(admissionBody).not.toBeNull())
    expect(settingsPatchBody).toEqual({ ask_apex: {
      selected_model: 'deepseek/deepseek-v4-flash-0731',
      cloud: { last_model: 'deepseek/deepseek-v4-flash-0731', effort: 'high' },
    } })
    expect(admissionBody).toMatchObject({
      profile_id: 'catch_up',
      model_id: 'deepseek/deepseek-v4-flash-0731',
      reasoning: 'high',
    })
    expect(appMocks.requestOperation).toHaveBeenCalledWith('generate_briefing_session', expect.objectContaining({
      model_id: 'deepseek/deepseek-v4-flash-0731',
      involves_cloud: true,
    }))
  })

  it('repeats a saved DEMO fixture profile without persisting its fixture model', async () => {
    appMocks.demoModeActive = true
    const fixtureId = '00000000-0000-4000-8000-000000000111'
    const newId = '00000000-0000-4000-8000-000000000112'
    const conversationId = '00000000-0000-4000-8000-000000000113'
    const newConversationId = '00000000-0000-4000-8000-000000000115'
    const fixtureSummary = {
      id: fixtureId,
      profile_id: 'catch_up',
      model_id: 'demo/daily-fixture',
      conversation_id: conversationId,
      run_id: 'fixture-run',
      run_status: 'failed',
      created_at: '2026-09-26T10:00:00Z',
      presented_at: null,
    }
    const newSummary = { ...fixtureSummary, id: newId, conversation_id: newConversationId, run_id: 'new-run', run_status: 'running', created_at: '2026-09-27T10:00:00Z' }
    const fixtureDetail = {
      id: fixtureId,
      conversation_id: conversationId,
      opening_message_id: '00000000-0000-4000-8000-000000000114',
      run_id: 'fixture-run',
      run_status: 'failed',
      run_error_code: 'fixture_unavailable',
      configuration: {
        profile: { id: 'catch_up', label: 'Catch Up', purpose: 'Changes.', definition_version: 2 },
        model: { model_id: 'demo/daily-fixture', provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
        origin: 'hud',
        execution_kind: 'demo',
      },
      artifact: null,
      evidence_count: 0,
      evidence_ids: [],
      created_at: fixtureSummary.created_at,
      presented_at: null,
      speech_status: 'not_requested',
    }
    const newDetail = { ...fixtureDetail, id: newId, conversation_id: newConversationId, run_id: 'new-run', run_status: 'running', run_error_code: null, created_at: newSummary.created_at }
    let postBody: Record<string, unknown> | null = null
    let patches = 0
    const conversationSummary = (id: string) => ({
      id,
      title: 'Demo briefing conversation',
      archived_at: null,
      agent: 'apex',
      selected_tool_names: [],
      tool_profile_id: null,
      updated_at: '2026-09-27T10:00:00Z',
    })
    const conversationDetail = (id: string) => ({ ...conversationSummary(id), active_leaf_message_id: null, messages: [] })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      const path = url.pathname
      if (path.endsWith('/briefing-profiles')) return new Response(JSON.stringify([
        { id: 'daily', label: 'Daily', purpose: 'Current.', investigation_required: false, available: true, unavailable_reason: null },
        { id: 'catch_up', label: 'Catch Up', purpose: 'Changes.', investigation_required: false, available: true, unavailable_reason: null },
        { id: 'deep', label: 'Deep', purpose: 'Investigate.', investigation_required: true, available: true, unavailable_reason: null },
      ]), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/settings') && init?.method === 'PATCH') patches += 1
      if (path.endsWith('/briefing-sessions') && init?.method === 'POST') {
        postBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify(newSummary), { status: 202, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith('/briefing-sessions')) {
        return new Response(JSON.stringify(postBody ? [newSummary, fixtureSummary] : [fixtureSummary]), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/briefing-sessions/${fixtureId}`)) return new Response(JSON.stringify(fixtureDetail), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/briefing-sessions/${newId}`)) return new Response(JSON.stringify(newDetail), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/cortex/conversations')) {
        const ids = postBody ? [conversationId, newConversationId] : [conversationId]
        return new Response(JSON.stringify(ids.map(conversationSummary)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path.endsWith(`/cortex/conversations/${conversationId}`)) return new Response(JSON.stringify(conversationDetail(conversationId)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith(`/cortex/conversations/${newConversationId}`)) return new Response(JSON.stringify(conversationDetail(newConversationId)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/cortex/tool-catalog')) return new Response(JSON.stringify(catalogFor('apex')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    const user = userEvent.setup()
    renderOverviewApp()
    await selectWorkspace(user, 'Briefing')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Repeat last briefing' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Repeat last briefing' }))

    await waitFor(() => expect(postBody).not.toBeNull())
    expect(postBody).toMatchObject({ profile_id: 'catch_up', model_id: 'demo/daily-fixture' })
    expect(postBody).not.toHaveProperty('reasoning')
    expect(patches).toBe(0)
    expect(appMocks.requestOperation).toHaveBeenCalledWith('generate_briefing_session', expect.objectContaining({
      model_id: 'demo/daily-fixture',
      involves_cloud: false,
    }))
  })
})
