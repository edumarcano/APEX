import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react'

import { type ApexLogoProps } from './components/ApexLogo'
import { CelestialBackground } from './components/CelestialBackground'
import { CortexWorkspace } from './components/CortexWorkspace'
import { ActivityInboxWorkspace } from './components/ActivityInboxWorkspace'
import { ApexAssistantRuntime, type ApexAssistantRunConfig, type ApexAssistantRuntimeHandle } from './components/ApexAssistantRuntime'
import { PreflightDialog } from './components/PreflightDialog'
import { ReminderReviewDialog } from './components/ReminderReviewDialog'
import { ReminderTaskDialog } from './components/ReminderTaskDialog'
import { CompletedRemindersDialog } from './components/CompletedRemindersDialog'
import SettingsPanel from './components/SettingsPanel'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { HomeWorkspace } from './components/home/HomeWorkspace'
import type { HomeIdentityProps } from './components/home/HomeIdentity'
import type { HomeTelemetryData } from './components/home/HomeTelemetry'
import { useApexData } from './hooks/useApexData'
import { useCortex } from './hooks/useCortex'
import { useActions } from './hooks/useActions'
import { useActivityInbox } from './hooks/useActivityInbox'
import { useAppActivation } from './hooks/useAppActivation'
import { useBriefingPipeline } from './hooks/useBriefingPipeline'
import { useBriefingSessions } from './hooks/useBriefingSessions'
import { resolveBriefingLayoutPhase, useHomeView } from './hooks/useHomeView'
import { useMarketData } from './hooks/useMarketData'
import { useMcpStatus } from './hooks/useMcpStatus'
import { usePreflight } from './hooks/usePreflight'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import { useTelemetrySnapshot } from './hooks/useTelemetrySnapshot'
import { useToolCatalog } from './hooks/useToolCatalog'
import { useToolPreflight } from './hooks/useToolPreflight'
import { useVoiceDelivery } from './hooks/useVoiceDelivery'
import { API_ENDPOINTS } from './lib/api'
import { requestVoiceCue } from './lib/voiceCues'
import { resolveAttentionStaggerMs, resolveTelemetryAttentionTier } from './lib/attentionTier'
import { resolveCalendarTelemetry } from './lib/calendarTelemetry'
import { resolveFootballTelemetry } from './lib/footballTelemetry'
import {
  resolveLogoVisualColors,
  resolveOuterShellActivity,
} from './lib/logoVisualState'
import { moduleReasonLabel, resolveModuleLedState } from './lib/moduleTelemetry'
import { DEFAULT_WEATHER_INFO, resolveWeatherFromModule } from './lib/weatherTelemetry'
import { filterAgentSettingsForDevMode } from './lib/settings'
import {
  resolveHomeQueryOverrides,
} from './lib/agents'
import type {
  AgentKey,
  CloudEffort,
  HostedTool,
  LocalReasoningMode,
  TelemetrySnapshot,
} from './types/telemetry'
import type { BriefingProfileId } from './types/briefings'
import type { ContextReview } from './types/context'
import type {
  CloudHostedToolsSettings,
  RuntimeSettings,
  SettingsResponse,
  VoiceMode,
} from './types/settings'

function sameToolNames(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((name) => right.includes(name))
}

const TELEMETRY_FRESHNESS_WINDOW_MS = 5 * 60 * 1000

function hasFreshUsableTelemetry(snapshot: TelemetrySnapshot): boolean {
  const collectedAt = Date.parse(snapshot.collected_at)
  const now = Date.now()
  const ageMs = now - collectedAt
  // Keep this aligned with core.telemetry.models.FRESHNESS_WINDOW_SECONDS.
  if (!Number.isFinite(collectedAt) || ageMs < 0 || ageMs >= TELEMETRY_FRESHNESS_WINDOW_MS) {
    return false
  }

  return Object.values(snapshot.modules).some((module) => {
    if (
      module.status === 'disabled' ||
      module.status === 'unavailable' ||
      module.freshness === 'stale' ||
      module.freshness === 'none' ||
      module.observed_at === null
    ) {
      return false
    }
    const observedAt = Date.parse(module.observed_at)
    const observedAgeMs = now - observedAt
    return Number.isFinite(observedAt) && observedAgeMs >= 0 && observedAgeMs < TELEMETRY_FRESHNESS_WINDOW_MS
  })
}

function marketSettingsChanged(previous: RuntimeSettings, next: RuntimeSettings): boolean {
  return previous.features.market !== next.features.market || previous.market.symbols.length !== next.market.symbols.length || previous.market.symbols.some((symbol, index) => symbol !== next.market.symbols[index])
}

interface ParsedEmail {
  subject: string
  time: string
}

function parseEmailTelemetry(emailText: string): { count: number; items: ParsedEmail[] } {
  if (!emailText || emailText.includes('No unread emails') || emailText.includes('bypassed')) {
    return { count: 0, items: [] }
  }
  const countMatch = emailText.match(/Email Telemetry:\s+(\d+)\s+unread/i)
  const count = countMatch ? parseInt(countMatch[1], 10) : 0
  const recentIndex = emailText.indexOf('Most recent: ')
  if (recentIndex < 0) return { count, items: [] }
  const recentStr = emailText.slice(recentIndex + 'Most recent: '.length)
  const matches = [...recentStr.matchAll(/'([^']+)'\s+at\s+([^,)]+)/g)]
  const items = matches.map((m) => ({
    subject: m[1],
    time: m[2].trim(),
  }))
  return { count, items }
}

interface ParsedNews {
  topic: string
  headline: string
}

function parseNewsTelemetry(newsText: string): ParsedNews[] {
  if (!newsText || !newsText.includes('[NEWS TELEMETRY]')) {
    return []
  }
  const cleanText = newsText.replace('[NEWS TELEMETRY]\n', '')
  const parts = cleanText.split(' | ')
  return parts.map((part) => {
    const match = part.match(/^\[([^\]]+)\]\s*(.+)$/)
    if (match) {
      return { topic: match[1], headline: match[2] }
    }
    return { topic: 'Global', headline: part }
  })
}


const VALID_VOICE_MODES: readonly VoiceMode[] = ['off', 'manual', 'automatic']

function isVoiceMode(value: string): value is VoiceMode {
  return (VALID_VOICE_MODES as readonly string[]).includes(value)
}

function applyAskApexSettings(
  askApex: SettingsResponse['settings']['ask_apex'],
  setters: {
    setCloudEffort: (effort: CloudEffort) => void
    setSelectedModel: (model: string) => void
    setSandboxMode: (enabled: boolean) => void
    setHostedTools: (tools: CloudHostedToolsSettings) => void
    setCloudPersonalContextEnabled: (enabled: boolean) => void
    setLocalPersonalContextEnabled: (enabled: boolean) => void
    setLocalContextWindow: (contextWindow: number) => void
    setLocalReasoningMode: (reasoningMode: LocalReasoningMode) => void
  },
): void {
  const cloud = askApex.cloud
  const local = askApex.local
  if (!cloud || !local) return
  setters.setCloudEffort(cloud.effort)
  setters.setSelectedModel(askApex.selected_model)
  setters.setSandboxMode(askApex.sandbox_mode)
  setters.setHostedTools({ ...cloud.hosted_tools })
  setters.setCloudPersonalContextEnabled(cloud.personal_context_enabled)
  setters.setLocalPersonalContextEnabled(local.personal_context_enabled)
  setters.setLocalContextWindow(local.context_window)
  setters.setLocalReasoningMode(local.reasoning_mode)
}

interface PersistAgentSettingsOptions {
  refreshToolCatalog?: boolean
}

export default function App(): ReactElement {
  const [reminderPulseCount, setReminderPulseCount] = useState(0)
  const [activeAgent] = useState<AgentKey>('apex')
  const [cloudEffort, setCloudEffort] = useState<CloudEffort>('medium')
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('automatic')
  const [workspace, setWorkspace] = useState<'home' | 'cortex' | 'inbox'>('home')
  const [dailyConversationReady, setDailyConversationReady] = useState<string | null>(null)
  const completedDailyHistoryRef = useRef(new Set<string>())
  const dailyOpenSequenceRef = useRef(0)
  const dailyOpeningSessionsRef = useRef(new Map<string, number>())
  const [lastAssistantWorkspace, setLastAssistantWorkspace] = useState<'home' | 'cortex'>('home')
  const navigateWorkspace = useCallback((nextWorkspace: 'home' | 'cortex' | 'inbox'): void => {
    if (nextWorkspace !== 'inbox') setLastAssistantWorkspace(nextWorkspace)
    setWorkspace(nextWorkspace)
  }, [])
  const [linkedReviewId, setLinkedReviewId] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState('deepseek/deepseek-v4-flash-0731')
  const [sandboxMode, setSandboxMode] = useState(false)
  const [hostedTools, setHostedTools] = useState<CloudHostedToolsSettings>({
    google_search: true,
    google_maps: true,
  })
  const [snapshotAttached, setSnapshotAttached] = useState(true)
  const [cloudPersonalContextEnabled, setCloudPersonalContextEnabled] = useState(false)
  const [localPersonalContextEnabled, setLocalPersonalContextEnabled] = useState(false)
  const [localContextWindow, setLocalContextWindow] = useState(16384)
  const [localReasoningMode, setLocalReasoningMode] = useState<LocalReasoningMode>('none')
  const [submissionPending, setSubmissionPending] = useState(false)
  const submissionPendingRef = useRef(false)
  const [toolProfileFeedback, setToolProfileFeedback] = useState<string | null>(null)
  const [toolProfileError, setToolProfileError] = useState<string | null>(null)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [isReminderReviewOpen, setIsReminderReviewOpen] = useState(false)
  const [isCompletedRemindersOpen, setIsCompletedRemindersOpen] = useState(false)
  const [reminderTaskDialog, setReminderTaskDialog] = useState<{
    id: string
    mode: 'edit' | 'delete'
  } | null>(null)
  const [isReminderRefreshPending, setIsReminderRefreshPending] = useState(false)
  const [reminderActionError, setReminderActionError] = useState<string | null>(null)
  const assistantRuntimeRef = useRef<ApexAssistantRuntimeHandle | null>(null)
  const [assistantRunning, setAssistantRunning] = useState(false)
  const [assistantRunningAgent, setAssistantRunningAgent] = useState<AgentKey | null>(null)
  const [assistantConversationId, setAssistantConversationId] = useState<string | null>(null)
  const [assistantConversationPreferences, setAssistantConversationPreferences] = useState<{
    agent: AgentKey
    selected_tool_names: string[] | null
    tool_profile_id: string | null
  } | null>(null)
  const [conversationHydrating, setConversationHydrating] = useState(false)
  const [assistantResponse, setAssistantResponse] = useState<Record<string, unknown> | null>(null)
  const [assistantResponseError, setAssistantResponseError] = useState<string | null>(null)
  const settingsButtonRef = useRef<HTMLButtonElement>(null)
  const activeAgentRef = useRef(activeAgent)
  useEffect(() => {
    activeAgentRef.current = activeAgent
  }, [activeAgent])

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const apexData = useApexData()
  const {
    activeReminders,
    reminderSourceState,
    createReminder,
    demoModeActive,
    devModeActive,
    agentQueriesEnabled,
    marketEnabled,
    voiceMode: bootVoiceMode,
    markReminderAsRead,
    getReminderTask,
    listCompletedReminders,
    updateReminderTask,
    deleteReminderTask,
    reopenReminderTask,
    refreshReminders,
    syncReminders,
    dismissUnknownReminder,
    applyBootSettings,
  } = apexData
  const activityPartition = sandboxMode ? 'sandbox' : 'production'
  const activityInbox = useActivityInbox(
    workspace === 'inbox' && !demoModeActive,
    activityPartition,
  )
  const actions = useActions(
    workspace === 'cortex' && !demoModeActive,
  )
  const { activated, activate, deactivate } = useAppActivation()
  const homeView = useHomeView({ activated, deactivate })
  const { selectView: selectHomeView } = homeView
  const homeBriefingOpen = workspace === 'home' && homeView.view === 'briefing'
  const preflight = usePreflight()
  const telemetry = useTelemetrySnapshot()
  const [marketSymbols, setMarketSymbols] = useState<readonly string[] | null>(null)
  const marketRevision = typeof telemetry.snapshot?.modules.market?.data.collection_revision === 'number'
    ? telemetry.snapshot.modules.market.data.collection_revision
    : null
  const { data: marketData, isLoading: isMarketDisplayLoading } = useMarketData(
    marketEnabled && activated,
    marketRevision,
    marketSymbols,
  )
  const briefing = useBriefingPipeline()
  const dailySessions = useBriefingSessions()
  const {
    openSession: openDailySession,
    generate: generateBriefing,
    cancelSession: cancelDailySession,
    hasActiveSession: hasActiveDailySession,
  } = dailySessions
  const voiceDelivery = useVoiceDelivery(
    briefing.briefing,
    briefing.status,
    briefing.isSpeaking,
  )

  const {
    cortexAgent,
    modelCatalog: fullModelCatalog,
    cortexAgentHydrated,
    isLocalModelActionPending,
    verifyingCloudModel,
    loadLocalModel,
    unloadLocalModel,
    verifyCloudAgent,
    refreshAgentsStatus,
  } = useCortex(true)
  const isCortexQuerying = assistantRunning
  const activeQueryAgent = assistantRunningAgent
  const cortexLatestTrace = assistantResponse && Array.isArray(assistantResponse.tool_trace)
    ? assistantResponse.tool_trace as Array<{ name: string; status: string; duration_ms: number }>
    : []
  const cortexError = assistantResponseError
  const cortexContextUsage = assistantResponse && assistantResponse.local_context_usage && typeof assistantResponse.local_context_usage === 'object'
    ? assistantResponse.local_context_usage as { estimated_prompt_tokens: number; peak_prompt_tokens: number | null; context_window: number; history_messages_dropped: number }
    : null
  const mcpRuntime = useMcpStatus(true)
  const mcpAvailabilityVersion = useMemo(() => {
    if (!mcpRuntime.status) return null
    return JSON.stringify({
      enabled: mcpRuntime.status.enabled,
      status: mcpRuntime.status.status,
      servers: mcpRuntime.status.servers.map((server) => ({
        id: server.id,
        status: server.status,
        registered_tools: server.registered_tools,
      })),
    })
  }, [mcpRuntime.status])

  const homeSelectedEntry = useMemo(
    () => fullModelCatalog.find((entry) => entry.model_id === selectedModel) ?? fullModelCatalog[0],
    [fullModelCatalog, selectedModel],
  )
  const homeOverrides = useMemo(
    () => resolveHomeQueryOverrides(homeSelectedEntry),
    [homeSelectedEntry],
  )

  const assistantWorkspace = workspace === 'inbox' ? lastAssistantWorkspace : workspace
  const usesHomeAssistantContract = assistantWorkspace === 'home'
  const effectiveWorkspaceAgent = usesHomeAssistantContract ? homeOverrides.agent : activeAgent
  const effectiveWorkspaceModel = usesHomeAssistantContract ? homeOverrides.modelId : selectedModel
  const effectiveWorkspaceRuntime = (usesHomeAssistantContract ? homeSelectedEntry : fullModelCatalog.find(
    (entry) => entry.model_id === selectedModel,
  ))?.runtime ?? 'cloud'
  const toolCatalogState = useToolCatalog(
    effectiveWorkspaceAgent,
    effectiveWorkspaceModel,
    effectiveWorkspaceRuntime,
    mcpAvailabilityVersion,
  )
  const toolPreflightState = useToolPreflight({
    agent: effectiveWorkspaceAgent,
    modelId: usesHomeAssistantContract ? homeOverrides.modelId : selectedModel,
    effort: usesHomeAssistantContract ? homeOverrides.effort : (homeSelectedEntry?.runtime === 'cloud' ? cloudEffort : null),
    contextWindow: usesHomeAssistantContract ? homeOverrides.contextWindow : null,
    localReasoningMode: usesHomeAssistantContract ? homeOverrides.localReasoningMode : null,
    selectedToolNames: toolCatalogState.selectedToolNames,
    toolProfileId: toolCatalogState.activeToolProfileId,
    prompt: '',
    conversationId: assistantConversationId,
    snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
    enabled: Boolean(
      workspace !== 'inbox' &&
      agentQueriesEnabled &&
      !toolCatalogState.isLoading &&
      toolCatalogState.selectionReady &&
      toolCatalogState.catalog?.agent === effectiveWorkspaceAgent,
    ),
  })

  const conversationHydrationRef = useRef<string | null>(null)
  const conversationHydrationTargetRef = useRef<{
    conversationId: string
    agent: AgentKey
    selectedToolNames: string[] | null
    toolProfileId: string | null
  } | null>(null)
  const conversationSelectionBaselineRef = useRef<{
    conversationId: string
    selectedToolNames: string[]
    toolProfileId: string | null
  } | null>(null)

  useEffect(() => {
    if (!assistantConversationId || !assistantConversationPreferences) {
      conversationHydrationRef.current = null
      conversationHydrationTargetRef.current = null
      conversationSelectionBaselineRef.current = null
      return
    }
    if (conversationHydrationRef.current === assistantConversationId) {
      queueMicrotask(() => setConversationHydrating(false))
      return
    }
    if (
      !toolCatalogState.selectionReady ||
      toolCatalogState.catalog?.agent !== activeAgent
    ) {
      return
    }
    const selectedToolNames = assistantConversationPreferences.selected_tool_names
    const namesToApply = selectedToolNames ?? toolCatalogState.selectedToolNames
    const selectionMatches =
      sameToolNames(namesToApply, toolCatalogState.selectedToolNames) &&
      assistantConversationPreferences.tool_profile_id === toolCatalogState.activeToolProfileId
    conversationHydrationTargetRef.current = {
      conversationId: assistantConversationId,
      agent: assistantConversationPreferences.agent,
      selectedToolNames,
      toolProfileId: assistantConversationPreferences.tool_profile_id,
    }
    if (!selectionMatches) {
      toolCatalogState.setToolSelection(namesToApply, assistantConversationPreferences.tool_profile_id)
      return
    }
    conversationHydrationRef.current = assistantConversationId
    conversationHydrationTargetRef.current = null
    conversationSelectionBaselineRef.current = {
      conversationId: assistantConversationId,
      selectedToolNames: toolCatalogState.selectedToolNames,
      toolProfileId: toolCatalogState.activeToolProfileId,
    }
    queueMicrotask(() => {
      if (conversationHydrationRef.current === assistantConversationId) setConversationHydrating(false)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Granular properties of toolCatalogState are tracked individually to prevent re-render thrashing.
  }, [
    activeAgent,
    assistantConversationPreferences,
    assistantConversationId,
    toolCatalogState.activeToolProfileId,
    toolCatalogState.catalog?.agent,
    toolCatalogState.selectedToolNames,
    toolCatalogState.selectionReady,
    toolCatalogState.setToolSelection,
  ])

  useEffect(() => {
    if (
      !assistantConversationId ||
      conversationHydrationRef.current !== assistantConversationId
    ) {
      return
    }
    if (!assistantConversationPreferences) return
    if (conversationHydrationTargetRef.current?.conversationId === assistantConversationId) {
      return
    }
    const baseline = conversationSelectionBaselineRef.current?.conversationId === assistantConversationId
      ? conversationSelectionBaselineRef.current
      : null
    const selectedNamesChanged = assistantConversationPreferences.selected_tool_names === null
      ? Boolean(baseline && (
        !sameToolNames(baseline.selectedToolNames, toolCatalogState.selectedToolNames) ||
        baseline.toolProfileId !== toolCatalogState.activeToolProfileId
      ))
      : !sameToolNames(assistantConversationPreferences.selected_tool_names, toolCatalogState.selectedToolNames) ||
        assistantConversationPreferences.tool_profile_id !== toolCatalogState.activeToolProfileId
    if (assistantConversationPreferences.agent === activeAgent && !selectedNamesChanged) {
      return
    }
    const conversationIdAtPatch = assistantConversationId
    void assistantRuntimeRef.current?.patchPreferences({
      agent: activeAgent,
      selectedToolNames: toolCatalogState.selectedToolNames,
      toolProfileId: toolCatalogState.activeToolProfileId,
    }).then((updated) => {
      if (!updated || assistantConversationId !== conversationIdAtPatch) return
      setAssistantConversationPreferences({
        agent: updated.agent,
        selected_tool_names: updated.selected_tool_names,
        tool_profile_id: updated.tool_profile_id,
      })
    })
  }, [
    activeAgent,
    assistantConversationId,
    assistantConversationPreferences,
    toolCatalogState.activeToolProfileId,
    toolCatalogState.selectedToolNames,
  ])

  useEffect(() => {
    if (bootVoiceMode && isVoiceMode(bootVoiceMode)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Mirrors asynchronous boot configuration into local controls.
      setVoiceMode(bootVoiceMode)
    }
  }, [bootVoiceMode])

  const handleSettingsApplied = useCallback(
    (response: SettingsResponse) => {
      applyBootSettings({
        agentQueriesEnabled: response.settings.ask_apex.enabled,
        agentInitialSelection: {
          runtime: response.settings.ask_apex.selected_model === response.settings.ask_apex.local.last_model ? 'local' : 'cloud',
          agent: 'apex',
          modelId: response.settings.ask_apex.selected_model,
          effort: null,
        },
        marketEnabled: response.settings.features.market,
      })
      applyAskApexSettings(response.settings.ask_apex, {
        setCloudEffort,
        setSelectedModel,
        setSandboxMode,
        setHostedTools,
        setCloudPersonalContextEnabled,
        setLocalPersonalContextEnabled,
        setLocalContextWindow,
        setLocalReasoningMode,
      })

      setVoiceMode(response.settings.voice.mode)
    },
    [applyBootSettings],
  )

  const handleSettingsPanelApplied = useCallback(
    async (response: SettingsResponse, previousSettings: RuntimeSettings) => {
      const shouldRefreshMarket = marketSettingsChanged(previousSettings, response.settings)
      const shouldRefreshCalendar = previousSettings.features.calendar !== response.settings.features.calendar || JSON.stringify(previousSettings.calendar) !== JSON.stringify(response.settings.calendar)
      if (shouldRefreshMarket) {
        setMarketSymbols(response.settings.market.symbols)
      }
      handleSettingsApplied(response)
      if (activated && shouldRefreshMarket) {
        await telemetry.refreshConnector('market', { force: true })
      }
      if (activated && shouldRefreshCalendar) {
        await telemetry.refreshConnector('calendar', { force: true })
      }
      await refreshAgentsStatus()
      await toolCatalogState.refreshCatalog()
    },
    [activated, handleSettingsApplied, refreshAgentsStatus, telemetry, toolCatalogState],
  )

  // Cortex remembers both production runtime choices. This is deliberately
  // separate from DEV_MODE's session-only sandbox override.
  useEffect(() => {
    const controller = new AbortController()
    void (async (): Promise<void> => {
      try {
        const response = await fetch(API_ENDPOINTS.settings, { signal: controller.signal })
        if (!response.ok || controller.signal.aborted) return
        const body: unknown = await response.json()
        if (!body || typeof body !== 'object') return
        const settings = (body as { settings?: unknown }).settings
        if (!settings || typeof settings !== 'object') return
        const settingsValues = settings as Record<string, unknown>
        const agentSettings = settingsValues.ask_apex
        if (agentSettings && typeof agentSettings === 'object') {
          const parsed = agentSettings as SettingsResponse['settings']['ask_apex']
          if (parsed.cloud && parsed.local) {
            applyAskApexSettings(parsed, {
              setCloudEffort,
              setSelectedModel,
              setSandboxMode,
              setHostedTools,
              setCloudPersonalContextEnabled,
              setLocalPersonalContextEnabled,
              setLocalContextWindow,
              setLocalReasoningMode,
            })
          }
        }

      } catch {
        // Cortex falls back to boot defaults when settings are temporarily unavailable.
      }
    })()
    return () => controller.abort()
  }, [])

  const {
    pipelineState,
    isSpeaking: isPipelineSpeaking,
    active_tts_engine,
    system_load_throttled,
  } = briefing
  const isSpeaking = isPipelineSpeaking || voiceDelivery.isSpeaking
  const resolvedTtsEngine = pipelineState?.active_tts_engine ?? active_tts_engine
  const resolvedSystemThrottled =
    pipelineState?.system_load_throttled ?? system_load_throttled
  const liveSynthesis = pipelineState?.synthesis
  const localLifecycleBusy =
    activeQueryAgent === 'apex' && homeSelectedEntry?.runtime === 'local' ||
    liveSynthesis?.phase === 'loading' ||
    liveSynthesis?.phase === 'generating'

  const activeStep = pipelineState?.step ?? null
  const isBriefingRunning = briefing.status === 'loading'
  const isRefreshingAll = telemetry.isRefreshingAll
  const isTelemetryCollecting =
    isRefreshingAll || telemetry.refreshingConnectors.size > 0
  const isMarketTelemetryRefreshing =
    isRefreshingAll || telemetry.refreshingConnectors.has('market')
  const isMarketLoading =
    isMarketDisplayLoading || (
      marketEnabled &&
      activated &&
      isMarketTelemetryRefreshing
    )

  const loadingLocalModel = useMemo(
    () => fullModelCatalog.find((model) => model.runtime === 'local' && model.loading) ?? null,
    [fullModelCatalog],
  )
  const activeLocalModel = useMemo(
    () =>
      fullModelCatalog.find(
        (model) => model.runtime === 'local' && model.active,
      ) ?? null,
    [fullModelCatalog],
  )
  const isLocalModelLoading =
    loadingLocalModel !== null ||
    (liveSynthesis?.loading === true &&
      (liveSynthesis.provider === 'llama_cpp' ||
        liveSynthesis.model_id !== null))
  const isLocalModelLoaded = activeLocalModel !== null
  const loadingDisplayName = useMemo(() => {
    if (liveSynthesis?.model_id) {
      return (
        fullModelCatalog.find((entry) => entry.model_id === liveSynthesis.model_id)?.display_name ??
        liveSynthesis.model_id
      )
    }
    const localEntry = homeSelectedEntry?.runtime === 'local'
      ? homeSelectedEntry
      : fullModelCatalog.find((entry) => entry.model_id === selectedModel && entry.runtime === 'local')
    return localEntry?.display_name ?? null
  }, [fullModelCatalog, homeSelectedEntry, liveSynthesis, selectedModel])
  const outerShellActivity = resolveOuterShellActivity({
    activeStep,
    isBriefingRunning,
    isLocalModelLoading,
    isTelemetryCollecting,
  })

  const visualColors = useMemo(
    () =>
      resolveLogoVisualColors({
        briefingStatus: briefing.status,
        activeStep,
        activated,
        isBriefingRunning,
        isCortexQuerying,
        isLocalModelLoading,
        isLocalModelLoaded,
        isSpeaking,
        isTelemetryCollecting,
      }),
    [
      briefing.status,
      activeStep,
      activated,
      isBriefingRunning,
      isCortexQuerying,
      isLocalModelLoading,
      isLocalModelLoaded,
      isSpeaking,
      isTelemetryCollecting,
    ],
  )
  const atmosphereGlowColor = visualColors.atmosphere
  const logoGlowColor = visualColors.logo

  const pendingReminderCount = activeReminders.length

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent): void => {
      const mouseX = event.clientX / window.innerWidth - 0.5
      const mouseY = event.clientY / window.innerHeight - 0.5
      document.documentElement.style.setProperty('--mouse-x', String(mouseX))
      document.documentElement.style.setProperty('--mouse-y', String(mouseY))
    }

    window.addEventListener('mousemove', handleMouseMove, { passive: true })
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
    }
  }, [])

  const handleStartApex = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('activate')
    if (resolution !== 'proceed') {
      return
    }

    activate()
    const localSnapshotIsReady = telemetry.snapshot !== null && hasFreshUsableTelemetry(telemetry.snapshot)
    const initialSnapshot = voiceMode === 'automatic' && !localSnapshotIsReady
      ? await telemetry.loadLatest()
      : telemetry.snapshot
    const telemetryWasReady = initialSnapshot !== null && hasFreshUsableTelemetry(initialSnapshot)
    const refreshPromise = telemetry.refreshAllWithOutcome({ force: false })
    const initialCuePromise = voiceMode === 'automatic'
      ? requestVoiceCue(telemetryWasReady ? 'activation_ready' : 'activation_loading')
      : Promise.resolve()
    const [outcome] = await Promise.all([refreshPromise, initialCuePromise])
    if (
      voiceMode === 'automatic' &&
      outcome.kind !== 'conflict' &&
      outcome.kind !== 'cancelled'
    ) {
      if (outcome.kind === 'failure') {
        await requestVoiceCue('activation_refresh_failed')
      } else if (!telemetryWasReady) {
        if (!hasFreshUsableTelemetry(outcome.snapshot)) {
          await requestVoiceCue('activation_no_fresh_telemetry')
        }
      }
    }
  }, [preflight, activate, telemetry, voiceMode])

  const openDailyConversation = useCallback(async (conversationId: string, completedSessionId?: string, expectedSequence?: number): Promise<boolean> => {
    const sequence = expectedSequence ?? ++dailyOpenSequenceRef.current
    const opened = await assistantRuntimeRef.current?.openConversation(conversationId) ?? false
    if (sequence !== dailyOpenSequenceRef.current) return false
    setDailyConversationReady(opened ? conversationId : null)
    if (opened && completedSessionId) completedDailyHistoryRef.current.add(completedSessionId)
    return opened
  }, [])

  const handleOpenDailySession = useCallback(async (sessionId: string): Promise<void> => {
    const sequence = ++dailyOpenSequenceRef.current
    dailyOpeningSessionsRef.current.set(sessionId, sequence)
    selectHomeView('briefing')
    setDailyConversationReady(null)
    try {
      const session = await openDailySession(sessionId)
      if (sequence !== dailyOpenSequenceRef.current) return
      await openDailyConversation(session.conversation_id, session.run_status === 'completed' ? session.id : undefined, sequence)
    } catch {
      if (sequence === dailyOpenSequenceRef.current) setDailyConversationReady(null)
    } finally {
      if (dailyOpeningSessionsRef.current.get(sessionId) === sequence) dailyOpeningSessionsRef.current.delete(sessionId)
    }
  }, [openDailySession, openDailyConversation, selectHomeView])

  const startBriefing = useCallback(async (profileId: BriefingProfileId, activateHome = false): Promise<void> => {
    if (hasActiveDailySession || (!agentQueriesEnabled && !demoModeActive)) return
    const sequence = ++dailyOpenSequenceRef.current
    const resolution = await preflight.requestOperation('generate_briefing_session', {
      model_id: selectedModel,
      involves_cloud: homeSelectedEntry?.runtime === 'cloud',
    })
    if (resolution !== 'proceed' || sequence !== dailyOpenSequenceRef.current) return
    if (activateHome) activate()
    selectHomeView('briefing')
    setDailyConversationReady(null)
    try {
      const summary = await generateBriefing(profileId, {
        modelId: selectedModel,
        reasoning: homeSelectedEntry?.runtime === 'cloud' ? cloudEffort : null,
        contextWindow: homeSelectedEntry?.runtime === 'local' ? localContextWindow : null,
        localReasoningMode: homeSelectedEntry?.runtime === 'local' ? localReasoningMode : null,
      })
      if (sequence !== dailyOpenSequenceRef.current) return
      dailyOpeningSessionsRef.current.set(summary.id, sequence)
      try {
        await openDailyConversation(summary.conversation_id, summary.run_status === 'completed' ? summary.id : undefined, sequence)
      } finally {
        if (dailyOpeningSessionsRef.current.get(summary.id) === sequence) dailyOpeningSessionsRef.current.delete(summary.id)
      }
    } catch {
      // The sessions hook retains the admission or generation failure for the Home panel.
    }
  }, [agentQueriesEnabled, activate, cloudEffort, generateBriefing, hasActiveDailySession, demoModeActive, homeSelectedEntry, localContextWindow, localReasoningMode, openDailyConversation, preflight, selectHomeView, selectedModel])

  const handleStartOverview = useCallback((): void => {
    selectHomeView('overview')
    void handleStartApex()
  }, [handleStartApex, selectHomeView])

  useEffect(() => {
    const handleGlobalEnter = (event: KeyboardEvent): void => {
      if (activated || preflight.dialogOpen || preflight.isChecking) {
        return
      }

      if (event.key !== 'Enter') {
        return
      }

      const target = event.target
      if (!(target instanceof HTMLElement)) {
        return
      }

      const tagName = target.tagName
      if (
        target.closest('button, a, select, [role="button"], [role="dialog"]') !== null ||
        tagName === 'INPUT' ||
        tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return
      }

      handleStartOverview()
    }

    window.addEventListener('keydown', handleGlobalEnter)
    return () => {
      window.removeEventListener('keydown', handleGlobalEnter)
    }
  }, [activated, handleStartOverview, preflight.dialogOpen, preflight.isChecking])

  const dailyControlsBusy = preflight.isChecking || preflight.dialogOpen || dailySessions.isGenerating
  const canGenerateDaily = Boolean(agentQueriesEnabled || demoModeActive)
  const isConnectorRefreshing = useCallback(
    (name: string): boolean => isRefreshingAll || telemetry.refreshingConnectors.has(name),
    [isRefreshingAll, telemetry.refreshingConnectors],
  )
  const handleRefreshConnector = useCallback(
    (name: string): void => {
      void telemetry.refreshConnector(name)
    },
    [telemetry],
  )
  const handleRefreshReminders = useCallback((): void => {
    if (isReminderRefreshPending) return
    setReminderActionError(null)
    setIsReminderRefreshPending(true)
    void refreshReminders().finally(() => setIsReminderRefreshPending(false))
  }, [isReminderRefreshPending, refreshReminders])
  const handleRefreshAll = useCallback((): void => {
    void telemetry.refreshAll({ force: false })
  }, [telemetry])

  const hasSnapshot = telemetry.snapshot !== null
  const weatherModule = telemetry.snapshot?.modules.weather
  const newsModule = telemetry.snapshot?.modules.news
  const emailModule = telemetry.snapshot?.modules.email
  const calendarModule = telemetry.snapshot?.modules.calendar
  const f1Module = telemetry.snapshot?.modules.f1
  const footballModule = telemetry.snapshot?.modules.football
  const remindersModule = telemetry.snapshot?.modules.reminders

  const attentionTiers = useMemo(() => {
    const options = {
      activated,
      isRefreshing: isRefreshingAll,
      hasSnapshot,
      briefingStatus: briefing.status,
      briefingStep: briefing.pipelineState?.step ?? null,
    }
    return {
      reminders: resolveTelemetryAttentionTier('reminders', options),
      weather: resolveTelemetryAttentionTier('weather', options),
      news: resolveTelemetryAttentionTier('news', options),
      events: resolveTelemetryAttentionTier('events', options),
      market: resolveTelemetryAttentionTier('market', options),
      inbox: resolveTelemetryAttentionTier('inbox', options),
      insights: resolveTelemetryAttentionTier('insights', options),
    }
  }, [activated, isRefreshingAll, hasSnapshot, briefing.status, briefing.pipelineState?.step])

  const attentionStagger = useMemo(
    () => ({
      reminders: resolveAttentionStaggerMs('reminders'),
      weather: resolveAttentionStaggerMs('weather'),
      news: resolveAttentionStaggerMs('news'),
      events: resolveAttentionStaggerMs('events'),
      market: resolveAttentionStaggerMs('market'),
      inbox: resolveAttentionStaggerMs('inbox'),
      insights: resolveAttentionStaggerMs('insights'),
    }),
    [],
  )

  const weatherRefreshing = isConnectorRefreshing('weather')
  const newsRefreshing = isConnectorRefreshing('news')
  const emailRefreshing = isConnectorRefreshing('email')
  const calendarRefreshing = isConnectorRefreshing('calendar')
  const f1Refreshing = isConnectorRefreshing('f1')
  const footballRefreshing = isConnectorRefreshing('football')
  const remindersRefreshing = isConnectorRefreshing('reminders') || isReminderRefreshPending

  const weatherLedState = resolveModuleLedState(weatherModule, weatherRefreshing)
  const newsLedState = resolveModuleLedState(newsModule, newsRefreshing)
  const emailLedState = resolveModuleLedState(emailModule, emailRefreshing)
  const calendarLedState = resolveModuleLedState(calendarModule, calendarRefreshing)
  const weatherStatusMessage = moduleReasonLabel(weatherModule)
  const newsStatusMessage = moduleReasonLabel(newsModule)
  const emailStatusMessage = moduleReasonLabel(emailModule)
  const remindersStatusMessage = moduleReasonLabel(remindersModule)
  const eventsStatusMessage = [
    ['Calendar', calendarModule] as const,
    ['F1', f1Module] as const,
    ['Football', footballModule] as const,
  ]
    .map(([label, module]) => {
      const reason = moduleReasonLabel(module)
      return reason ? `${label}: ${reason}` : null
    })
    .filter((value): value is string => value !== null)
    .join(' · ') || null

  const weatherInfo = weatherModule
    ? resolveWeatherFromModule(weatherModule)
    : DEFAULT_WEATHER_INFO
  const weatherBody = (() => {
    const detail = weatherInfo.detail.trim()
    if (detail.length > 0) {
      return detail
    }
    if (weatherRefreshing) {
      return 'Loading weather…'
    }
    return 'Weather unavailable.'
  })()


  const handleMarkReminderRead = (id: string): void => {
    setReminderActionError(null)
    void markReminderAsRead(id).catch((error: unknown) => {
      const code = error instanceof Error ? error.message : 'reminder_completion_failed'
      const actionId = error && typeof error === 'object' && 'actionId' in error
        ? String((error as { actionId?: unknown }).actionId ?? '')
        : ''
      const message = code === 'reminder_target_changed'
        ? 'Reminder changed in Microsoft To Do. Refresh and try again.'
        : code === 'microsoft_todo_unavailable'
          ? 'Microsoft To Do is unavailable. The reminder was restored.'
          : 'Could not complete the reminder. The reminder was restored.'
      setReminderActionError(actionId ? `${message} Review action ${actionId}.` : message)
    })
  }

  const handleReminderSave = useCallback(async (text: string): Promise<'synced' | 'pending' | 'unknown'> => {
    const outcome = await createReminder(text)
    setReminderPulseCount((previous) => previous + 1)
    return outcome
  }, [createReminder])

  useEffect(() => {
    const session = dailySessions.activeSession
    if (!homeBriefingOpen || !session || dailySessions.selectedSessionId !== session.id || session.run_status !== 'completed' || !session.artifact) return
    if (completedDailyHistoryRef.current.has(session.id) && assistantConversationId === session.conversation_id) return
    if (dailyOpeningSessionsRef.current.has(session.id)) return
    const sequence = ++dailyOpenSequenceRef.current
    dailyOpeningSessionsRef.current.set(session.id, sequence)
    void openDailyConversation(session.conversation_id, session.id, sequence).finally(() => {
      if (dailyOpeningSessionsRef.current.get(session.id) === sequence) dailyOpeningSessionsRef.current.delete(session.id)
    })
  }, [assistantConversationId, homeBriefingOpen, dailySessions.activeSession, dailySessions.selectedSessionId, openDailyConversation])

  const handleCancelDailySession = useCallback((sessionId: string): void => {
    void cancelDailySession(sessionId).catch(() => undefined)
  }, [cancelDailySession])

  const logoStatus =
    !activated
      ? 'idle'
      : briefing.status === 'loading' || briefing.status === 'error' || briefing.status === 'success'
        ? briefing.status
        : isRefreshingAll
          ? 'loading'
          : 'success'
  const cortexLogoProps: Omit<ApexLogoProps, 'className'> = {
    step: activeStep,
    status: logoStatus,
    isSpeaking,
    reminderPulseCount,
    isCortexQuerying,
    isTelemetryCollecting,
    outerShellActivity,
  }

  const f1ScheduleTelemetryText = f1Module?.display_text?.trim() ?? ''
  const emailInfo = parseEmailTelemetry(emailModule?.display_text ?? '')
  const newsItems = parseNewsTelemetry(newsModule?.display_text ?? '')
  const calendarInfo = resolveCalendarTelemetry(calendarModule)
  const footballInfo = resolveFootballTelemetry(footballModule)

  const eventsCompactValue = hasSnapshot
    ? [
        calendarInfo.totalCount > 0 ? `${calendarInfo.totalCount} calendar` : null,
        footballInfo.fixtures.length > 0 ? `${footballInfo.fixtures.length} football` : null,
      ].filter((value): value is string => value !== null).join(' · ') || 'No events'
    : null
  const inboxCompactValue = hasSnapshot ? `${emailInfo.count} unread` : null
  const newsCompactValue = hasSnapshot ? `${newsItems.length} headlines` : null
  const remindersCompactValue = `${pendingReminderCount} pending`
  const runAssistantPreflight = useCallback(async (config: ApexAssistantRunConfig): Promise<boolean> => {
    if (submissionPendingRef.current) return false
    submissionPendingRef.current = true
    setSubmissionPending(true)
    try {
      const resolution = await preflight.requestOperation('cortex_query', {
        model_id: config.modelId ?? selectedModel,
      })
      return resolution === 'proceed'
    } finally {
      submissionPendingRef.current = false
      setSubmissionPending(false)
    }
  }, [preflight, selectedModel])

  const refreshToolCatalog = toolCatalogState.refreshCatalog
  const persistAgentSettings = useCallback(
    async (
      agentSettings: Record<string, unknown>,
      options: PersistAgentSettingsOptions = {},
    ): Promise<boolean> => {
      const payload = devModeActive ? filterAgentSettingsForDevMode(agentSettings) : agentSettings
      if (Object.keys(payload).length === 0) {
        return true
      }
      try {
        const response = await fetch(API_ENDPOINTS.settings, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ask_apex: payload }),
        })
        if (!response.ok) {
          return false
        }
        const body: unknown = await response.json()
        const settings = body && typeof body === 'object'
          ? (body as { settings?: SettingsResponse['settings'] }).settings
          : undefined
        if (settings?.ask_apex?.cloud && settings.ask_apex.local) {
          handleSettingsApplied({ settings } as SettingsResponse)
          await refreshAgentsStatus()
          if (options.refreshToolCatalog) {
            await refreshToolCatalog()
          }
        }
        return settings !== undefined
      } catch {
        // The session selection remains usable if local preference persistence fails.
        return false
      }
    },
    [
      devModeActive,
      handleSettingsApplied,
      refreshAgentsStatus,
      refreshToolCatalog,
    ],
  )

  const handleHomeModelChange = useCallback((modelId: string): void => {
    const model = fullModelCatalog.find((entry) => entry.model_id === modelId)
    if (!model) return
    setSelectedModel(modelId)
    if (model.runtime === 'cloud') {
      void persistAgentSettings({ selected_model: modelId, cloud: { last_model: modelId } }, { refreshToolCatalog: true })
    } else {
      void persistAgentSettings({ selected_model: modelId, local: { last_model: modelId } }, { refreshToolCatalog: true })
    }
    window.localStorage.removeItem('apex_home_selected_model_id')
  }, [fullModelCatalog, persistAgentSettings])


  const mutateToolProfile = useCallback(
    async (
      endpoint: string,
      method: 'POST' | 'PATCH' | 'DELETE',
      body?: Record<string, unknown>,
      successMessage = 'Tool profile updated.',
    ): Promise<Record<string, unknown> | null> => {
      setToolProfileError(null)
      setToolProfileFeedback(null)
      try {
        const response = await fetch(endpoint, {
          method,
          ...(body
            ? {
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
              }
            : {}),
        })
        const responseBody: unknown = await response.json().catch(() => null)
        if (!response.ok) {
          const detail = responseBody && typeof responseBody === 'object' && 'detail' in responseBody
            ? (responseBody as { detail?: unknown }).detail
            : null
          const message = typeof detail === 'string'
            ? detail
            : detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message?: unknown }).message === 'string'
              ? (detail as { message: string }).message
              : `Tool profile request failed (${response.status}).`
          setToolProfileError(message)
          return null
        }
        await toolCatalogState.refreshCatalog()
        setToolProfileFeedback(successMessage)
        return responseBody && typeof responseBody === 'object'
          ? responseBody as Record<string, unknown>
          : {}
      } catch {
        setToolProfileError('Tool profile request failed. Check the API connection and try again.')
        return null
      }
    },
    [toolCatalogState],
  )

  const saveToolProfile = useCallback(
    (name: string): void => {
      const currentProfile = toolCatalogState.catalog?.profiles.find(
        (profile) => profile.id === toolCatalogState.activeToolProfileId,
      )
      const endpoint = currentProfile && !currentProfile.built_in
        ? API_ENDPOINTS.cortexToolProfile(currentProfile.id)
        : API_ENDPOINTS.cortexToolProfiles
      const method = currentProfile && !currentProfile.built_in ? 'PATCH' : 'POST'
      void mutateToolProfile(
        endpoint,
        method,
        currentProfile && !currentProfile.built_in
          ? { name, tool_names: toolCatalogState.selectedToolNames }
          : { name, tool_names: toolCatalogState.selectedToolNames },
        currentProfile && !currentProfile.built_in
          ? 'Updated the active tool profile.'
          : 'Saved and activated the new tool profile.',
      ).then((responseBody) => {
        if (!responseBody || method !== 'POST') return
        const affectedProfileId = responseBody.affected_profile_id
        if (typeof affectedProfileId === 'string' && affectedProfileId.length > 0) {
          toolCatalogState.setToolSelection(
            toolCatalogState.selectedToolNames,
            affectedProfileId,
          )
        }
      })
    },
    [mutateToolProfile, toolCatalogState],
  )

  const duplicateToolProfile = useCallback(
    (profileId: string, name: string): void => {
      const profile = toolCatalogState.catalog?.profiles.find(
        (item) => item.id === profileId,
      )
      if (!profile) return
      void mutateToolProfile(API_ENDPOINTS.cortexToolProfiles, 'POST', {
        name,
        description: profile.description,
        tool_names: toolCatalogState.selectedToolNames,
      }, 'Duplicated the current resolved tool selection.').then((responseBody) => {
        if (!responseBody) return
        const affectedProfileId = responseBody.affected_profile_id
        if (typeof affectedProfileId === 'string' && affectedProfileId.length > 0) {
          toolCatalogState.setToolSelection(
            toolCatalogState.selectedToolNames,
            affectedProfileId,
          )
        }
      })
    },
    [mutateToolProfile, toolCatalogState],
  )

  const renameToolProfile = useCallback(
    (profileId: string, name: string): void => {
      void mutateToolProfile(API_ENDPOINTS.cortexToolProfile(profileId), 'PATCH', {
        name,
      }, 'Renamed the tool profile.')
    },
    [mutateToolProfile],
  )

  const deleteToolProfile = useCallback(
    (profileId: string): void => {
      void mutateToolProfile(API_ENDPOINTS.cortexToolProfile(profileId), 'DELETE', undefined, 'Deleted the tool profile.')
        .then((responseBody) => {
          if (responseBody) {
            toolCatalogState.setToolSelection(toolCatalogState.selectedToolNames, null)
          }
        })
    },
    [mutateToolProfile, toolCatalogState],
  )

  const restoreToolProfile = useCallback(
    (profileId: string): void => {
      toolCatalogState.applyToolProfile(profileId)
      setToolProfileError(null)
      setToolProfileFeedback('Reapplied the saved tool profile to the current selection.')
    },
    [toolCatalogState],
  )

  const setDefaultToolProfile = useCallback(
    (profileId: string): void => {
      void mutateToolProfile(API_ENDPOINTS.cortexToolProfileDefault, 'POST', {
        runtime: fullModelCatalog.find((entry) => entry.model_id === selectedModel)?.runtime ?? 'cloud',
        profile_id: profileId,
      }, 'Set as the default profile for this runtime.')
    },
    [fullModelCatalog, mutateToolProfile, selectedModel],
  )


  const handleModelChange = useCallback((model: string): void => {
    setSelectedModel(model)
    const entry = fullModelCatalog.find((item) => item.model_id === model)
    let nextEffort = cloudEffort
    if (entry?.reasoning_options && entry.reasoning_options.length > 0) {
      if (!entry.reasoning_options.includes(cloudEffort)) {
        nextEffort = entry.default_reasoning ?? entry.reasoning_options[0] ?? 'medium'
        setCloudEffort(nextEffort)
      }
    }
    const runtimePatch = entry?.runtime === 'local'
      ? { local: { last_model: model } }
      : { cloud: { last_model: model, effort: nextEffort } }
    void persistAgentSettings({
      selected_model: model, ...runtimePatch,
    }, { refreshToolCatalog: true })
  }, [cloudEffort, fullModelCatalog, persistAgentSettings])

  const handleEffortChange = useCallback((effort: CloudEffort): void => {
    setCloudEffort(effort)
    void persistAgentSettings(
      { cloud: { effort } },
      { refreshToolCatalog: false },
    )
  }, [persistAgentSettings])

  const handleHostedToolChange = useCallback((tool: HostedTool, enabled: boolean): void => {
    setHostedTools((current) => ({ ...current, [tool]: enabled }))
    void persistAgentSettings(
      { cloud: { hosted_tools: { [tool]: enabled } } },
      { refreshToolCatalog: true },
    )
  }, [persistAgentSettings])

  const handleSandboxModeChange = useCallback((enabled: boolean): void => {
    setSandboxMode(enabled)
    void persistAgentSettings({ sandbox_mode: enabled }, { refreshToolCatalog: true })
  }, [persistAgentSettings])

  const handleOpenActivityReview = useCallback(async (review: ContextReview): Promise<string | null> => {
    const currentPartition = sandboxMode ? 'sandbox' : 'production'
    if (review.partition !== currentPartition) {
      return `This linked review belongs to ${review.partition}. Switch partitions yourself before opening it.`
    }
    try {
      const response = await fetch(API_ENDPOINTS.cortexContextReview(review.id))
      if (!response.ok) return 'This linked review is no longer available in the current partition.'
    } catch {
      return 'This linked review could not be reached. Refresh the Inbox and try again.'
    }
    setLinkedReviewId(review.id)
    navigateWorkspace('cortex')
    return null
  }, [navigateWorkspace, sandboxMode])

  const handleLocalContextWindowChange = useCallback((
    contextWindow: number,
  ): Promise<boolean> => {
    return persistAgentSettings(
      {
        local: { context_window: contextWindow },
      },
      { refreshToolCatalog: true },
    )
  }, [persistAgentSettings])

  const handleLocalReasoningModeChange = useCallback((
    reasoningMode: LocalReasoningMode,
  ): Promise<boolean> => {
    return persistAgentSettings(
      {
        local: { reasoning_mode: reasoningMode },
      },
      { refreshToolCatalog: false },
    )
  }, [persistAgentSettings])

  const handleAssistantConversationChange = useCallback((summary: {
    id: string
    agent: AgentKey
    selected_tool_names: string[] | null
    tool_profile_id: string | null
  } | null): void => {
    setAssistantConversationId(summary?.id ?? null)
    setAssistantConversationPreferences(summary ? {
      agent: summary.agent,
      selected_tool_names: summary.selected_tool_names,
      tool_profile_id: summary.tool_profile_id,
    } : null)
    setConversationHydrating(Boolean(summary))
    setAssistantResponse(null)
    setAssistantResponseError(null)
  }, [])

  const handleAssistantRunningChange = useCallback((running: boolean, agent: AgentKey | null): void => {
    setAssistantRunning(running)
    setAssistantRunningAgent(agent)
  }, [])

  const handleAssistantResponseChange = useCallback((response: Record<string, unknown> | null, error: string | null): void => {
    setAssistantResponse(response)
    setAssistantResponseError(error)
    if (response) {
      void actions.refresh()
    }
  }, [actions])

  const briefingPhase = resolveBriefingLayoutPhase({
    session: dailySessions.activeSession,
    selectedSession: dailySessions.sessions.find((session) => session.id === dailySessions.selectedSessionId) ?? null,
    isGenerating: dailySessions.isGenerating,
  })
  const briefingEvidence = useMemo(() => ({
    evidenceById: dailySessions.evidenceById,
    loadingIds: dailySessions.evidenceLoadingIds,
    errors: dailySessions.evidenceErrors,
    onLoadEvidence: dailySessions.loadEvidence,
  }), [dailySessions.evidenceById, dailySessions.evidenceErrors, dailySessions.evidenceLoadingIds, dailySessions.loadEvidence])
  const homeIdentity: HomeIdentityProps = {
    logoProps: cortexLogoProps,
    glyphProps: {
      step: activeStep,
      status: logoStatus,
      isSpeaking,
      activeTtsEngine: resolvedTtsEngine,
      systemLoadThrottled: resolvedSystemThrottled,
      isCortexQuerying,
      isLocalModelLoading,
      loadingDisplayName,
      isTelemetryCollecting,
    },
  }
  const homeTelemetry: HomeTelemetryData = {
    hasSnapshot,
    isRefreshingAll,
    onRefreshConnector: handleRefreshConnector,
    attentionTiers,
    attentionStagger,
    weather: {
      info: weatherInfo,
      body: weatherBody,
      ledState: weatherLedState,
      statusMessage: weatherStatusMessage,
      showAttribution: weatherModule?.status === 'healthy',
    },
    events: {
      f1Text: f1ScheduleTelemetryText,
      ledState: calendarLedState,
      statusMessage: eventsStatusMessage,
      compactValue: eventsCompactValue,
      calendar: calendarInfo,
      football: footballInfo,
      footballModule,
      calendarRefreshing,
      f1Refreshing,
      footballRefreshing,
    },
    market: { data: marketData, isLoading: isMarketLoading, enabled: marketEnabled },
    inbox: {
      ledState: emailLedState,
      statusMessage: emailStatusMessage,
      compactValue: inboxCompactValue,
      count: emailInfo.count,
      items: emailInfo.items,
      refreshing: emailRefreshing,
    },
    news: {
      ledState: newsLedState,
      statusMessage: newsStatusMessage,
      compactValue: newsCompactValue,
      items: newsItems,
      refreshing: newsRefreshing,
    },
    reminders: {
      ledState: resolveModuleLedState(remindersModule, remindersRefreshing),
      statusMessage: remindersStatusMessage,
      compactValue: remindersCompactValue,
      items: activeReminders,
      sourceState: reminderSourceState ?? null,
      actionError: reminderActionError,
      refreshDisabled: isRefreshingAll || isReminderRefreshPending,
      onRefresh: handleRefreshReminders,
      onOpenCompleted: () => setIsCompletedRemindersOpen(true),
      onSave: handleReminderSave,
      onMarkRead: handleMarkReminderRead,
      onEdit: (id) => setReminderTaskDialog({ id, mode: 'edit' }),
      onDelete: (id) => setReminderTaskDialog({ id, mode: 'delete' }),
      onReview: () => setIsReminderReviewOpen(true),
    },
  }

  return (
    <main
      className="hud-app-shell hud-layout-fullscreen relative isolate flex h-dvh w-full min-h-0 flex-col overflow-x-hidden bg-[var(--hud-bg)] p-4 md:p-6"
      style={{
        '--atmosphere-glow-color': atmosphereGlowColor,
        '--logo-glow-color': logoGlowColor,
      } as CSSProperties}
    >
      <CelestialBackground />

      <div
        className="absolute inset-0 z-[var(--z-reactive-glow)] pointer-events-none overflow-hidden"
      >
        {/* Layer 1: Horizontal Drifting Nebula (Clockwise Swirl) */}
        <div className="absolute top-[-30%] left-[-30%] h-[160%] w-[160%] opacity-40 bg-nebula-swirl-1 animate-nebula-spin-clockwise" />

        {/* Layer 2: Vertical Drifting Aurora (Counter-Clockwise Swirl) */}
        <div className="absolute bottom-[-30%] right-[-30%] h-[160%] w-[160%] opacity-35 bg-nebula-swirl-2 animate-nebula-spin-counter" />

        {/* Layer 3: Vignette Edge Contrast Mask */}
        <div className="absolute inset-0 bg-atmosphere-vignette" />
      </div>

      <div className="hud-main-shell relative z-[var(--z-bento-hud)] flex min-h-0 flex-1 flex-col overflow-visible xl:overflow-hidden">
        <header className="hud-header relative pointer-events-none mb-4 flex h-20 w-full shrink-0 select-none flex-nowrap items-center">
          <SystemDiagnostics
            diagnostics={diagnostics}
            diagnosticsStatus={diagnosticsStatus}
            failedConnectors={telemetry.snapshot?.failed_connectors ?? briefing.failedConnectors}
            connectorHealth={telemetry.snapshot?.connector_health ?? briefing.connectorHealth}
            isCheckingConnectors={isRefreshingAll}
            refreshingConnectors={telemetry.refreshingConnectors}
            onRefreshConnectors={handleRefreshAll}
            demoModeActive={demoModeActive}
            devModeActive={devModeActive}
            onOpenSettings={() => setIsSettingsOpen(true)}
            settingsButtonRef={settingsButtonRef}
            workspaceNavigation={<nav className="flex items-center justify-center gap-1" aria-label="Workspace">
            <button type="button" onClick={() => navigateWorkspace('inbox')} aria-pressed={workspace === 'inbox'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'inbox' ? 'bg-[#FBBF24]/15 text-[#FFF3B0]' : 'text-zinc-500 hover:text-zinc-200'}`}>Inbox</button>
            <button type="button" onClick={() => navigateWorkspace('home')} aria-pressed={workspace === 'home'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'home' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'text-zinc-500 hover:text-zinc-200'}`}>Home</button>
            <button type="button" onClick={() => navigateWorkspace('cortex')} aria-pressed={workspace === 'cortex'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'cortex' ? 'bg-[#7E22CE]/25 text-[#D8B4FE]' : 'text-zinc-500 hover:text-zinc-200'}`}>Cortex</button>
          </nav>}
          />
        </header>

        <SettingsPanel
          open={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          restoreFocusRef={settingsButtonRef}
          status={briefing.status}
          pipelineStep={activeStep}
          isSpeaking={isSpeaking}
          isCortexQuerying={isCortexQuerying}
          modelCatalog={fullModelCatalog}
          cortexAgentHydrated={cortexAgentHydrated}
          failedConnectors={briefing.failedConnectors}
          hasBriefingEvidence={briefing.status === 'success' || briefing.status === 'error'}
          onApplied={handleSettingsPanelApplied}
          mcpRuntime={mcpRuntime}
        />

        <ApexAssistantRuntime
          key={`${demoModeActive ? 'demo' : devModeActive && sandboxMode ? 'sandbox' : 'production'}`}
          config={{
            agent: effectiveWorkspaceAgent,
            effort: effectiveWorkspaceRuntime === 'cloud' ? (usesHomeAssistantContract ? homeOverrides.effort : cloudEffort) : null,
            modelId: effectiveWorkspaceModel,
            contextWindow: effectiveWorkspaceRuntime === 'local' ? (usesHomeAssistantContract ? homeOverrides.contextWindow : localContextWindow) : null,
            localReasoningMode: effectiveWorkspaceRuntime === 'local' ? (usesHomeAssistantContract ? homeOverrides.localReasoningMode : localReasoningMode) : null,
            selectedToolNames: toolCatalogState.selectedToolNames,
            toolProfileId: toolCatalogState.activeToolProfileId,
            snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
          }}
          beforeRun={runAssistantPreflight}
          runtimeRef={assistantRuntimeRef}
          onConversationChange={handleAssistantConversationChange}
          onRunningChange={handleAssistantRunningChange}
          onResponseChange={handleAssistantResponseChange}
        >
        {workspace === 'home' ? (
          <HomeWorkspace
            view={homeView.view}
            briefingPhase={briefingPhase}
            identity={homeIdentity}
            telemetry={homeTelemetry}
            standbyActions={{
              onStartOverview: handleStartOverview,
              onStartBriefing: () => void startBriefing('daily', true),
              disabled: preflight.isChecking,
              briefingDisabled: !canGenerateDaily || dailySessions.hasActiveSession,
            }}
            briefingControls={{
              profiles: dailySessions.profiles,
              profileId: homeView.profileId,
              onProfileChange: homeView.setProfileId,
              selectedModelId: selectedModel,
              modelCatalog: fullModelCatalog,
              onModelChange: handleHomeModelChange,
              canGenerate: canGenerateDaily,
              busy: dailyControlsBusy,
              hasActiveSession: dailySessions.hasActiveSession,
              isGenerating: dailySessions.isGenerating,
              onGenerate: (profileId) => void startBriefing(profileId),
              onCancel: handleCancelDailySession,
              sessions: dailySessions.sessions,
              selectedSessionId: dailySessions.selectedSessionId,
              isLoadingSessions: dailySessions.isLoadingSessions,
              onOpenSession: (sessionId) => void handleOpenDailySession(sessionId),
              activeSession: dailySessions.activeSession,
              error: dailySessions.error,
              activeLocalModel,
              loadingLocalModel,
              localLifecycleBusy,
              onUnloadLocalModel: unloadLocalModel,
            }}
            briefingConversation={{
              ready: dailyConversationReady === dailySessions.activeSession?.conversation_id && assistantConversationId === dailySessions.activeSession?.conversation_id,
              canFollowUp: Boolean(agentQueriesEnabled) && !demoModeActive,
              session: dailySessions.activeSession,
              isLoadingSession: dailySessions.isLoadingSession,
              evidence: briefingEvidence,
              onMarkPresented: dailySessions.markPresented,
              onOpenConversation: (conversationId) => void openDailyConversation(conversationId),
            }}
            onSelectView={selectHomeView}
            onReturnToStandby={homeView.returnToStandby}
          />
        ) : workspace === 'cortex' ? (
          <CortexWorkspace
            activeAgent={activeAgent}
            cloudEffort={cloudEffort}
            selectedModel={selectedModel}
            localContextWindow={localContextWindow}
            localReasoningMode={localReasoningMode}
            hostedTools={hostedTools}
            devModeActive={devModeActive}
            sandboxMode={sandboxMode}
            agentQueriesEnabled={Boolean(agentQueriesEnabled)}
            cortexAgent={cortexAgent}
            latestTrace={cortexLatestTrace}
            error={cortexError}
            contextUsage={cortexContextUsage}
            toolCatalog={toolCatalogState.catalog}
            selectedToolNames={toolCatalogState.selectedToolNames}
            activeToolProfileId={toolCatalogState.activeToolProfileId}
            selectionReady={toolCatalogState.selectionReady}
            submissionPending={submissionPending}
            conversationHydrating={conversationHydrating}
            onToolSelectionChange={toolCatalogState.setSelectedToolNames}
            onToolProfileChange={toolCatalogState.applyToolProfile}
            toolPreflight={toolPreflightState.estimate}
            toolPreflightLoading={toolPreflightState.isLoading}
            toolCatalogError={toolCatalogState.error}
            toolPreflightError={toolPreflightState.error}
            toolProfileFeedback={toolProfileFeedback}
            toolProfileError={toolProfileError}
            onSaveToolProfile={saveToolProfile}
            onDuplicateToolProfile={duplicateToolProfile}
            onRenameToolProfile={renameToolProfile}
            onDeleteToolProfile={deleteToolProfile}
            onRestoreToolProfile={restoreToolProfile}
            onSetDefaultToolProfile={setDefaultToolProfile}
            isQuerying={isCortexQuerying}
            logoProps={cortexLogoProps}
            lifecycleBusy={localLifecycleBusy}
            lifecycleActionPending={isLocalModelActionPending}
            verifyingCloudModel={verifyingCloudModel}
            onLoadLocalModel={loadLocalModel}
            onUnloadLocalModel={unloadLocalModel}
            onVerifyCloudAgent={verifyCloudAgent}
            snapshotAttached={snapshotAttached}
            snapshotAvailable={telemetry.snapshot !== null}
            onSnapshotAttachedChange={setSnapshotAttached}
            personalContextEnabled={homeSelectedEntry?.runtime === 'local' ? localPersonalContextEnabled : cloudPersonalContextEnabled}
            onPersonalContextEnabledChange={(enabled) => persistAgentSettings(homeSelectedEntry?.runtime === 'local' ? { local: { personal_context_enabled: enabled } } : { cloud: { personal_context_enabled: enabled } })}
            onModelChange={handleModelChange}
            onEffortChange={handleEffortChange}
            onHostedToolChange={handleHostedToolChange}
            onSandboxModeChange={handleSandboxModeChange}
            onLocalContextWindowChange={handleLocalContextWindowChange}
            onLocalReasoningModeChange={handleLocalReasoningModeChange}
            actions={actions}
            demoModeActive={demoModeActive}
            assistantRunConfig={{
              agent: activeAgent,
              effort: homeSelectedEntry?.runtime === 'cloud' ? cloudEffort : null,
              modelId: selectedModel,
              contextWindow: homeSelectedEntry?.runtime === 'local' ? localContextWindow : null,
              localReasoningMode: homeSelectedEntry?.runtime === 'local' ? localReasoningMode : null,
              selectedToolNames: toolCatalogState.selectedToolNames,
              toolProfileId: toolCatalogState.activeToolProfileId,
              snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
            }}
            onAssistantPreflight={runAssistantPreflight}
            linkedReviewId={linkedReviewId}
          />
        ) : (
          <ActivityInboxWorkspace
            inbox={activityInbox}
            demoModeActive={demoModeActive}
            sandboxMode={sandboxMode}
            onOpenReview={handleOpenActivityReview}
          />
      )}
        </ApexAssistantRuntime>
      {isReminderReviewOpen ? (
        <ReminderReviewDialog
          reminders={activeReminders}
          onClose={() => setIsReminderReviewOpen(false)}
          onSync={syncReminders}
          onDismissUnknown={dismissUnknownReminder}
        />
      ) : null}
      {reminderTaskDialog ? (
        <ReminderTaskDialog
          id={reminderTaskDialog.id}
          mode={reminderTaskDialog.mode}
          onClose={() => setReminderTaskDialog(null)}
          onLoad={getReminderTask}
          onUpdate={updateReminderTask}
          onDelete={deleteReminderTask}
        />
      ) : null}
      {isCompletedRemindersOpen ? (
        <CompletedRemindersDialog
          onClose={() => setIsCompletedRemindersOpen(false)}
          onLoad={listCompletedReminders}
          onReopen={reopenReminderTask}
        />
      ) : null}
      </div>

      <PreflightDialog
        open={preflight.dialogOpen}
        operation={preflight.pendingOperation}
        warnings={preflight.warnings}
        blockers={preflight.blockers}
        isChecking={preflight.isChecking}
        error={preflight.error}
        onChoice={preflight.resolveDialog}
      />
    </main>
  )
}
