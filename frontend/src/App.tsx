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
import { ActivityReportsWorkspace } from './components/ActivityReportsWorkspace'
import { ApexAssistantRuntime, type ApexAssistantRunConfig, type ApexAssistantRuntimeHandle } from './components/ApexAssistantRuntime'
import { PreflightDialog } from './components/PreflightDialog'
import { ReminderReviewDialog } from './components/ReminderReviewDialog'
import { ReminderTaskDialog } from './components/ReminderTaskDialog'
import { CompletedRemindersDialog } from './components/CompletedRemindersDialog'
import SettingsPanel from './components/SettingsPanel'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { HudWorkspace } from './components/HudWorkspace'
import { BriefingSpeechControl } from './components/briefing/BriefingSpeechControl'
import type { BriefingSetupDraft } from './components/briefing/BriefingProfilePanel'
import { WorkspaceTabs, type WorkspacePeer } from './components/WorkspaceTabs'
import { LaunchView } from './components/LaunchView'
import type { HudIdentityProps } from './components/overview/HudIdentity'
import type { HudTelemetryData } from './components/overview/HudTelemetry'
import { useApexData } from './hooks/useApexData'
import { useCortex } from './hooks/useCortex'
import { useActions } from './hooks/useActions'
import { useActivityReports } from './hooks/useActivityReports'
import { useTelemetryCollectionState } from './hooks/useTelemetryCollectionState'
import { useBriefingSpeech } from './hooks/useBriefingSpeech'
import { useBriefingSessions } from './hooks/useBriefingSessions'
import { resolveBriefingLayoutPhase, useWorkspaceView, type WorkspaceHudDestination } from './hooks/useWorkspaceView'
import { useMarketData } from './hooks/useMarketData'
import { useMcpStatus } from './hooks/useMcpStatus'
import { usePreflight } from './hooks/usePreflight'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import { useTelemetrySnapshot, type RefreshAllOutcome } from './hooks/useTelemetrySnapshot'
import { useToolCatalog } from './hooks/useToolCatalog'
import { useToolPreflight } from './hooks/useToolPreflight'
import { API_ENDPOINTS } from './lib/api'
import { requestVoiceCue, willCollectFreshTelemetry } from './lib/voiceCues'
import { resolveAttentionStaggerMs, resolveTelemetryAttentionTier } from './lib/attentionTier'
import { resolveActiveBriefingActivity, resolveBriefingLogoActivity, resolveBriefingVisualState } from './lib/briefingVisualState'
import { resolveCalendarTelemetry } from './lib/calendarTelemetry'
import { resolveFootballTelemetry } from './lib/footballTelemetry'
import {
  resolveLogoVisualColors,
  resolveOuterShellActivity,
} from './lib/logoVisualState'
import { moduleReasonLabel, resolveModuleLedState } from './lib/moduleTelemetry'
import { DEFAULT_WEATHER_INFO, resolveWeatherFromModule } from './lib/weatherTelemetry'
import { resolveEmailTelemetry } from './lib/emailTelemetry'
import { resolveNewsTelemetry } from './lib/newsTelemetry'
import { filterAgentSettingsForDevMode } from './lib/settings'
import {
  resolveAgentTurnOverrides,
} from './lib/agents'
import type {
  AgentKey,
  CloudEffort,
  HostedTool,
  LocalReasoningMode,
  ModelCatalogEntry,
  TelemetrySnapshot,
} from './types/telemetry'
import type { BriefingSessionStatus, BriefingSpeechEngine } from './types/briefings'
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

const BRIEFING_ACTIVE_STATUSES: ReadonlySet<BriefingSessionStatus> = new Set(['queued', 'running', 'cancelling'])
const TELEMETRY_FRESHNESS_WINDOW_MS = 5 * 60 * 1000

function hasUsableTelemetry(snapshot: TelemetrySnapshot | null): boolean {
  if (!snapshot) return false
  const now = Date.now()
  const collectedAt = Date.parse(snapshot.collected_at)
  const collectedAgeMs = now - collectedAt
  if (!Number.isFinite(collectedAt) || collectedAgeMs < 0 || collectedAgeMs >= TELEMETRY_FRESHNESS_WINDOW_MS) {
    return false
  }

  return Object.values(snapshot.modules).some((module) => {
    if (
      (module.status !== 'healthy' && module.status !== 'degraded') ||
      module.freshness === 'stale' ||
      module.freshness === 'none' ||
      module.observed_at === null
    ) return false
    const observedAt = Date.parse(module.observed_at)
    const observedAgeMs = now - observedAt
    return Number.isFinite(observedAt) && observedAgeMs >= 0 && observedAgeMs < TELEMETRY_FRESHNESS_WINDOW_MS
  })
}

function marketSettingsChanged(previous: RuntimeSettings, next: RuntimeSettings): boolean {
  return previous.features.market !== next.features.market || previous.market.symbols.length !== next.market.symbols.length || previous.market.symbols.some((symbol, index) => symbol !== next.market.symbols[index])
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
  const [autoGenerateHighlights, setAutoGenerateHighlights] = useState<boolean>(() => {
    try {
      return localStorage.getItem('apex_auto_generate_speech') === 'true'
    } catch {
      return false
    }
  })
  const [voiceEngine, setVoiceEngine] = useState<BriefingSpeechEngine>('google')
  const handleAutoGenerateHighlightsChange = useCallback((enabled: boolean): void => {
    setAutoGenerateHighlights(enabled)
    try {
      localStorage.setItem('apex_auto_generate_speech', String(enabled))
    } catch {
      // Local storage unavailable
    }
  }, [])
  const [workspace, setWorkspace] = useState<WorkspacePeer>('overview')
  const [isLaunch, setIsLaunch] = useState(true)
  const [hasCollectedTelemetry, setHasCollectedTelemetry] = useState(false)
  const [overviewState, setOverviewState] = useState<'center' | 'collecting' | 'ready' | 'error' | 'no-data'>('center')
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [briefingTelemetryCollectionState, setBriefingTelemetryCollectionState] = useState<'idle' | 'collecting' | 'error' | 'no-data'>('idle')
  const [briefingTelemetryCollectionError, setBriefingTelemetryCollectionError] = useState<string | null>(null)
  const [briefingConversationReady, setBriefingConversationReady] = useState<string | null>(null)
  const [briefingSetupAutoOpen, setBriefingSetupAutoOpen] = useState(false)
  const completedBriefingHistoryRef = useRef(new Set<string>())
  const briefingOpenSequenceRef = useRef(0)
  const briefingOpeningSessionsRef = useRef(new Map<string, number>())
  const briefingOperationRef = useRef(false)
  const [lastAssistantWorkspace, setLastAssistantWorkspace] = useState<Exclude<WorkspacePeer, 'reports'>>('overview')
  const [hudDestination, setHudDestination] = useState<WorkspaceHudDestination>('overview')
  const navigateWorkspace = useCallback((nextWorkspace: WorkspacePeer): void => {
    setIsLaunch(false)
    if (nextWorkspace === 'overview' || nextWorkspace === 'briefing') setHudDestination(nextWorkspace)
    if (nextWorkspace !== 'reports') setLastAssistantWorkspace(nextWorkspace)
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
  const [assistantActivityLabel, setAssistantActivityLabel] = useState<string | null>(null)
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
    remindersLoadState,
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
  const activityReports = useActivityReports(
    workspace === 'reports' && !demoModeActive,
    activityPartition,
  )
  const actions = useActions(
    workspace === 'cortex' && !demoModeActive,
  )
  const { collectionStarted, startCollection } = useTelemetryCollectionState()
  const workspaceView = useWorkspaceView({ destination: hudDestination })
  const selectHudPeer = navigateWorkspace
  const briefingWorkspaceOpen = workspace === 'briefing' && workspaceView.view === 'briefing'
  const preflight = usePreflight()
  const telemetry = useTelemetrySnapshot()
  useEffect(() => {
    if (hasCollectedTelemetry || !hasUsableTelemetry(telemetry.snapshot)) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A usable snapshot from any refresh path latches the session's collected state.
    setHasCollectedTelemetry(true)
  }, [hasCollectedTelemetry, telemetry.snapshot])
  const [marketSymbols, setMarketSymbols] = useState<readonly string[] | null>(null)
  const marketRevision = typeof telemetry.snapshot?.modules.market?.data.collection_revision === 'number'
    ? telemetry.snapshot.modules.market.data.collection_revision
    : null
  const { data: marketData, isLoading: isMarketDisplayLoading } = useMarketData(
    marketEnabled && collectionStarted,
    marketRevision,
    marketSymbols,
  )
  const briefingSessions = useBriefingSessions()
  const refreshBriefingSessions = briefingSessions.refreshSessions
  const previousBriefingWorkspaceOpenRef = useRef(false)
  useEffect(() => {
    if (briefingWorkspaceOpen && !previousBriefingWorkspaceOpenRef.current) {
      void refreshBriefingSessions()
    }
    previousBriefingWorkspaceOpenRef.current = briefingWorkspaceOpen
  }, [briefingWorkspaceOpen, refreshBriefingSessions])
  const currentSelectedSession = briefingSessions.activeSession
  const selectedCompletedBriefing = currentSelectedSession && currentSelectedSession.id === briefingSessions.selectedSessionId &&
    currentSelectedSession.run_status === 'completed' && currentSelectedSession.artifact
    ? currentSelectedSession
    : null
  const announceHighlightsOutcome = useCallback((outcome: 'ready' | 'failed'): void => {
    if (voiceMode !== 'automatic') return
    void requestVoiceCue(outcome === 'ready' ? 'highlights_ready' : 'highlights_failed')
  }, [voiceMode])
  const briefingSpeech = useBriefingSpeech(selectedCompletedBriefing?.id ?? null, voiceMode, announceHighlightsOutcome)
  const {
    openSession: openBriefingSession,
    generate: generateBriefing,
    cancelSession: cancelBriefingSession,
    hasActiveSession: hasActiveBriefingSession,
    refreshLatestSession: refreshLatestBriefingSession,
  } = briefingSessions
  const {
    cortexAgent,
    modelCatalog: fullModelCatalog,
    cortexAgentHydrated,
    isLocalModelActionPending,
    verifyingCloudModel,
    loadLocalModel,
    unloadLocalModel,
    verifyCloudModel,
    refreshAgentsStatus,
  } = useCortex(true)
  const agentDisplayName = cortexAgent?.display_name?.trim() || 'Lynx'
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

  const sharedAgentModelEntry = useMemo(
    () => fullModelCatalog.find((entry) => entry.model_id === selectedModel) ?? fullModelCatalog[0],
    [fullModelCatalog, selectedModel],
  )
  const agentTurnOverrides = useMemo(
    () => resolveAgentTurnOverrides(sharedAgentModelEntry, {
      effort: cloudEffort,
      contextWindow: localContextWindow,
      localReasoningMode,
    }),
    [cloudEffort, sharedAgentModelEntry, localContextWindow, localReasoningMode],
  )

  const assistantWorkspace = workspace === 'reports' ? lastAssistantWorkspace : workspace
  const usesSharedAgentTurn = assistantWorkspace !== 'cortex'
  const effectiveWorkspaceAgent = usesSharedAgentTurn ? agentTurnOverrides.agent : activeAgent
  const effectiveWorkspaceModel = usesSharedAgentTurn ? agentTurnOverrides.modelId : selectedModel
  const effectiveWorkspaceRuntime = (usesSharedAgentTurn ? sharedAgentModelEntry : fullModelCatalog.find(
    (entry) => entry.model_id === selectedModel,
  ))?.runtime ?? 'cloud'
  const toolCatalogState = useToolCatalog(
    effectiveWorkspaceAgent,
    effectiveWorkspaceModel,
    effectiveWorkspaceRuntime,
    mcpAvailabilityVersion,
  )
  const refreshToolCatalog = toolCatalogState.refreshCatalog
  const toolPreflightState = useToolPreflight({
    agent: effectiveWorkspaceAgent,
    modelId: usesSharedAgentTurn ? agentTurnOverrides.modelId : selectedModel,
    effort: usesSharedAgentTurn ? agentTurnOverrides.effort : (sharedAgentModelEntry?.runtime === 'cloud' ? cloudEffort : null),
    contextWindow: usesSharedAgentTurn ? agentTurnOverrides.contextWindow : null,
    localReasoningMode: usesSharedAgentTurn ? agentTurnOverrides.localReasoningMode : null,
    selectedToolNames: toolCatalogState.selectedToolNames,
    toolProfileId: toolCatalogState.activeToolProfileId,
    prompt: '',
    conversationId: assistantConversationId,
    snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
    enabled: Boolean(
      workspace !== 'reports' &&
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
      if (response.settings.voice?.engine) {
        setVoiceEngine(response.settings.voice.engine)
      }
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
      if (collectionStarted && shouldRefreshMarket) {
        await telemetry.refreshConnector('market', { force: true })
      }
      if (collectionStarted && shouldRefreshCalendar) {
        await telemetry.refreshConnector('calendar', { force: true })
      }
      await refreshAgentsStatus()
      await toolCatalogState.refreshCatalog()
    },
    [collectionStarted, handleSettingsApplied, refreshAgentsStatus, telemetry, toolCatalogState],
  )

  const saveBriefingModelSettings = useCallback(async (
    draft: BriefingSetupDraft,
    model: ModelCatalogEntry,
  ): Promise<{
    modelId: string
    reasoning?: string
    contextWindow?: number
    localReasoningMode?: LocalReasoningMode
  }> => {
    const modelReasoningOptions = model.runtime === 'cloud' ? model.reasoning_options ?? [] : []
    const modelReasoningModes = model.runtime === 'local'
      ? model.reasoning_modes ?? (model.default_reasoning_mode ? [model.default_reasoning_mode] : [])
      : []
    let agentSettings: Record<string, unknown>
    if (model.runtime === 'cloud') {
      if (modelReasoningOptions.length > 0 && (!draft.cloudEffort || !modelReasoningOptions.includes(draft.cloudEffort))) {
        throw new Error('Choose a reasoning effort supported by this cloud model.')
      }
      agentSettings = {
        selected_model: model.model_id,
        cloud: {
          last_model: model.model_id,
          ...(modelReasoningOptions.length > 0 ? { effort: draft.cloudEffort } : {}),
        },
      }
    } else {
      if (!draft.localReasoningMode || !modelReasoningModes.includes(draft.localReasoningMode)) {
        throw new Error('Choose a reasoning mode supported by this local model.')
      }
      agentSettings = {
        selected_model: model.model_id,
        local: {
          last_model: model.model_id,
          reasoning_mode: draft.localReasoningMode,
        },
      }
    }

    const payload = devModeActive ? filterAgentSettingsForDevMode(agentSettings) : agentSettings
    let response: Response
    try {
      response = await fetch(API_ENDPOINTS.settings, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ask_apex: payload }),
      })
    } catch {
      throw new Error('Briefing settings could not be saved. Check the API connection and try again.')
    }
    const responseBody: unknown = await response.json().catch(() => null)
    const detail = responseBody && typeof responseBody === 'object' && 'detail' in responseBody
      ? (responseBody as { detail?: unknown }).detail
      : null
    if (!response.ok) {
      const message = typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message?: unknown }).message === 'string'
          ? (detail as { message: string }).message
          : 'Briefing settings could not be saved.'
      throw new Error(message)
    }
    const settings = responseBody && typeof responseBody === 'object'
      ? (responseBody as { settings?: SettingsResponse['settings'] }).settings
      : undefined
    const resolved = settings?.ask_apex
    if (!settings || !resolved?.cloud || !resolved.local) {
      throw new Error(`Briefing settings were saved without a usable ${agentDisplayName} configuration response.`)
    }

    handleSettingsApplied({ settings } as SettingsResponse)
    void Promise.allSettled([refreshAgentsStatus(), refreshToolCatalog()])

    if (resolved.selected_model !== model.model_id) {
      throw new Error('The saved model changed while the briefing was being prepared. Review the selected model and try again.')
    }
    if (model.runtime === 'cloud') {
      if (modelReasoningOptions.length > 0 && (!modelReasoningOptions.includes(resolved.cloud.effort) || resolved.cloud.effort !== draft.cloudEffort)) {
        throw new Error('The saved cloud reasoning effort changed while the briefing was being prepared. Review the selection and try again.')
      }
      return {
        modelId: resolved.selected_model,
        ...(modelReasoningOptions.length > 0 ? { reasoning: resolved.cloud.effort } : {}),
      }
    }
    if (!modelReasoningModes.includes(resolved.local.reasoning_mode) || resolved.local.reasoning_mode !== draft.localReasoningMode) {
      throw new Error('The saved local reasoning mode changed while the briefing was being prepared. Review the selection and try again.')
    }
    const contextWindow = model.provider === 'llama_cpp' && model.context_options?.includes(resolved.local.context_window)
      ? resolved.local.context_window
      : undefined
    return {
      modelId: resolved.selected_model,
      contextWindow,
      localReasoningMode: resolved.local.reasoning_mode,
    }
  }, [agentDisplayName, devModeActive, handleSettingsApplied, refreshAgentsStatus, refreshToolCatalog])

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

        const voiceSettings = settingsValues.voice
        if (voiceSettings && typeof voiceSettings === 'object') {
          const engine = (voiceSettings as { engine?: string }).engine
          if (engine === 'google' || engine === 'kokoro' || engine === 'pyttsx3') {
            setVoiceEngine(engine)
          }
        }
      } catch {
        // Cortex falls back to boot defaults when settings are temporarily unavailable.
      }
    })()
    return () => controller.abort()
  }, [])

  const selectedBriefingVisual = resolveBriefingVisualState(currentSelectedSession)
  const activeBriefingActivity = useMemo(
    () => resolveActiveBriefingActivity({
      sessions: briefingSessions.sessions,
      selectedSessionId: briefingSessions.selectedSessionId,
      selectedSession: currentSelectedSession,
      modelCatalog: fullModelCatalog,
    }),
    [currentSelectedSession, briefingSessions.selectedSessionId, briefingSessions.sessions, fullModelCatalog],
  )
  const activeBriefingDetail = activeBriefingActivity.session &&
    briefingSessions.selectedSessionId === activeBriefingActivity.session.id &&
    currentSelectedSession?.id === activeBriefingActivity.session.id
    ? currentSelectedSession
    : briefingSessions.activeRunDetail?.id === activeBriefingActivity.session?.id
      ? briefingSessions.activeRunDetail
      : null
  const activeBriefingVisual = resolveBriefingVisualState(activeBriefingDetail)
  const briefingStatus = activeBriefingActivity.isRunning ? 'loading' : selectedBriefingVisual.status
  const activeStep = activeBriefingActivity.isRunning ? activeBriefingVisual.step : selectedBriefingVisual.step
  const isSpeaking = briefingSpeech.speech?.status === 'playing'
  const isPreparingSpeech = briefingSpeech.speech?.status === 'preparing' || briefingSpeech.pendingAction === 'prepare'
  const logoActivity = resolveBriefingLogoActivity({
    activeRun: activeBriefingActivity.isRunning,
    activeActivity: activeBriefingVisual.activity,
    selectedActivity: selectedBriefingVisual.activity,
    isPreparingSpeech,
    isSpeaking,
  })
  const resolvedTtsEngine = briefingSpeech.speech?.engine ?? voiceEngine ?? 'google'
  const resolvedSystemThrottled = false
  const localLifecycleBusy =
    (activeQueryAgent === 'apex' && sharedAgentModelEntry?.runtime === 'local') ||
    activeBriefingActivity.isLocalModelRunning ||
    (briefingSessions.isGenerating && sharedAgentModelEntry?.runtime === 'local')

  const isBriefingRunning = briefingStatus === 'loading'
  const isRefreshingAll = telemetry.isRefreshingAll
  const isTelemetryCollecting =
    isRefreshingAll || telemetry.refreshingConnectors.size > 0
  const isMarketTelemetryRefreshing =
    isRefreshingAll || telemetry.refreshingConnectors.has('market')
  const isMarketLoading =
    isMarketDisplayLoading || (
      marketEnabled &&
      collectionStarted &&
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
  const isLocalModelLoading = loadingLocalModel !== null
  const isLocalModelLoaded = activeLocalModel !== null
  const loadingDisplayName = useMemo(() => {
    const localEntry = loadingLocalModel ?? (sharedAgentModelEntry?.runtime === 'local'
        ? sharedAgentModelEntry
        : fullModelCatalog.find((entry) => entry.model_id === selectedModel && entry.runtime === 'local'))
    return localEntry?.display_name ?? null
  }, [fullModelCatalog, loadingLocalModel, sharedAgentModelEntry, selectedModel])
  const outerShellActivity = resolveOuterShellActivity({
    activity: logoActivity,
    isLocalModelLoading,
    isTelemetryCollecting,
  })

  const visualColors = useMemo(
    () =>
      resolveLogoVisualColors({
        activity: logoActivity,
        briefingStatus,
        isCortexQuerying,
        isLocalModelLoading,
        isLocalModelLoaded,
        isSpeaking,
        isTelemetryCollecting,
      }),
    [
      briefingStatus,
      logoActivity,
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

  const handleCollectTelemetry = useCallback(async (onCollectionStarted?: () => void, onOutcome?: (outcome: RefreshAllOutcome) => void): Promise<boolean> => {
    const resolution = await preflight.requestOperation('activate')
    if (resolution !== 'proceed') {
      return false
    }

    setOverviewError(null)
    setOverviewState('collecting')
    startCollection()
    onCollectionStarted?.()
    // The reuse check must finish first; a live refresh would make the snapshot look reusable.
    const announceCollection = voiceMode === 'automatic' && await willCollectFreshTelemetry()
    const refreshPromise = telemetry.refreshAllWithOutcome({ force: false })
    const initialCuePromise = announceCollection
      ? requestVoiceCue('activation_loading')
      : Promise.resolve()
    const [outcome] = await Promise.all([refreshPromise, initialCuePromise])
    onOutcome?.(outcome)
    if (outcome.kind === 'success') {
      if (hasUsableTelemetry(outcome.snapshot)) {
        setHasCollectedTelemetry(true)
        setOverviewState('ready')
      } else {
        setOverviewState('no-data')
      }
    } else if (outcome.kind === 'failure') {
      setOverviewState('error')
      setOverviewError(outcome.error)
    } else {
      setOverviewState('center')
    }
    if (
      voiceMode === 'automatic' &&
      outcome.kind !== 'conflict' &&
      outcome.kind !== 'cancelled'
    ) {
      if (outcome.kind === 'failure') {
        await requestVoiceCue('activation_refresh_failed')
      } else if (!hasUsableTelemetry(outcome.snapshot)) {
        await requestVoiceCue('activation_no_fresh_telemetry')
      } else {
        await requestVoiceCue('activation_ready')
      }
    }
    return true
  }, [preflight, startCollection, telemetry, voiceMode])

  const openBriefingConversation = useCallback(async (conversationId: string, completedSessionId?: string, expectedSequence?: number): Promise<boolean> => {
    const sequence = expectedSequence ?? ++briefingOpenSequenceRef.current
    const opened = await assistantRuntimeRef.current?.openConversation(conversationId) ?? false
    if (sequence !== briefingOpenSequenceRef.current) return false
    setBriefingConversationReady(opened ? conversationId : null)
    if (opened && completedSessionId) completedBriefingHistoryRef.current.add(completedSessionId)
    return opened
  }, [])

  const handleOpenBriefingSession = useCallback(async (sessionId: string): Promise<void> => {
    const sequence = ++briefingOpenSequenceRef.current
    briefingOpeningSessionsRef.current.set(sessionId, sequence)
    selectHudPeer('briefing')
    setBriefingConversationReady(null)
    try {
      const session = await openBriefingSession(sessionId)
      if (sequence !== briefingOpenSequenceRef.current) return
      await openBriefingConversation(session.conversation_id, session.run_status === 'completed' ? session.id : undefined, sequence)
    } catch {
      if (sequence === briefingOpenSequenceRef.current) setBriefingConversationReady(null)
    } finally {
      if (briefingOpeningSessionsRef.current.get(sessionId) === sequence) briefingOpeningSessionsRef.current.delete(sessionId)
    }
  }, [openBriefingSession, openBriefingConversation, selectHudPeer])

  const briefingCueSessionsRef = useRef(new Set<string>())
  const autoSpeechSessionsRef = useRef(new Set<string>())
  const announceBriefingOutcome = useCallback((status: BriefingSessionStatus): void => {
    if (status === 'completed') void requestVoiceCue('briefing_ready')
    else if (status === 'failed' || status === 'interrupted') void requestVoiceCue('briefing_failed')
  }, [])
  const briefingSessionList = briefingSessions.sessions
  useEffect(() => {
    // Only sessions started in this page session are announced, once, when they leave an active status.
    if (voiceMode !== 'automatic') {
      briefingCueSessionsRef.current.clear()
      return
    }
    for (const session of briefingSessionList) {
      if (!briefingCueSessionsRef.current.has(session.id) || BRIEFING_ACTIVE_STATUSES.has(session.run_status)) continue
      briefingCueSessionsRef.current.delete(session.id)
      announceBriefingOutcome(session.run_status)
    }
  }, [announceBriefingOutcome, briefingSessionList, voiceMode])

  useEffect(() => {
    if (voiceMode === 'off') {
      autoSpeechSessionsRef.current.clear()
      return
    }
    if (
      autoGenerateHighlights &&
      selectedCompletedBriefing &&
      autoSpeechSessionsRef.current.has(selectedCompletedBriefing.id)
    ) {
      const speechStatus = briefingSpeech.speech?.status
      if (speechStatus === 'not_requested') {
        autoSpeechSessionsRef.current.delete(selectedCompletedBriefing.id)
        void briefingSpeech.prepare()
      } else if (speechStatus && speechStatus !== 'preparing') {
        autoSpeechSessionsRef.current.delete(selectedCompletedBriefing.id)
      }
    }
  }, [autoGenerateHighlights, briefingSpeech, selectedCompletedBriefing, voiceMode])

  const performBriefingGeneration = useCallback(async (draft: BriefingSetupDraft): Promise<void> => {
    if (hasActiveBriefingSession) throw new Error('A briefing is already running.')
    if (!agentQueriesEnabled && !demoModeActive) throw new Error(`Briefings are disabled in ${agentDisplayName} settings.`)
    const sequence = ++briefingOpenSequenceRef.current
    const model = fullModelCatalog.find((entry) => entry.model_id === draft.modelId)
    if (!demoModeActive && (!model || model.credentials_configured === false || model.status === 'disabled' || !['available', 'configured', 'verified', 'unknown', undefined].includes(model.status))) {
      throw new Error(`The selected ${agentDisplayName} model is not currently available.`)
    }
    const selectedProfile = briefingSessions.profiles.find((entry) => entry.id === draft.profileId)
    if (selectedProfile && !selectedProfile.available) {
      throw new Error(selectedProfile.unavailable_reason ?? `${selectedProfile.label} is unavailable.`)
    }
    if (demoModeActive && draft.profileId === 'deep') throw new Error('Deep is unavailable in DEMO_MODE.')

    const requestModelId = demoModeActive ? 'demo/daily-fixture' : draft.modelId
    const resolution = await preflight.requestOperation('generate_briefing_session', {
      model_id: requestModelId,
      involves_cloud: !demoModeActive && model?.runtime === 'cloud',
    })
    if (resolution !== 'proceed' || sequence !== briefingOpenSequenceRef.current) {
      throw new Error(resolution === 'blocked'
        ? 'Preflight blocked this briefing. Review the blocker, then try again.'
        : 'Briefing setup was kept open because preflight was cancelled.')
    }

    let generationOptions: { modelId: string; reasoning?: string; contextWindow?: number; localReasoningMode?: LocalReasoningMode }
    if (demoModeActive) {
      generationOptions = { modelId: 'demo/daily-fixture' }
    } else {
      if (!model) throw new Error(`The selected ${agentDisplayName} model is no longer available.`)
      generationOptions = await saveBriefingModelSettings(draft, model)
    }

    selectHudPeer('briefing')
    setBriefingConversationReady(null)
    const summary = await generateBriefing(draft.profileId, generationOptions)
    if (autoGenerateHighlights && voiceMode !== 'off') {
      autoSpeechSessionsRef.current.add(summary.id)
    }
    if (voiceMode === 'automatic') {
      if (BRIEFING_ACTIVE_STATUSES.has(summary.run_status)) {
        briefingCueSessionsRef.current.add(summary.id)
        void requestVoiceCue('briefing_generating', { briefingProfile: draft.profileId })
      } else {
        announceBriefingOutcome(summary.run_status)
      }
    }
    workspaceView.setProfileId(draft.profileId)
    briefingOpeningSessionsRef.current.set(summary.id, sequence)
    void openBriefingConversation(summary.conversation_id, summary.run_status === 'completed' ? summary.id : undefined, sequence)
      .catch(() => false)
      .finally(() => {
        if (briefingOpeningSessionsRef.current.get(summary.id) === sequence) briefingOpeningSessionsRef.current.delete(summary.id)
      })
  }, [
    agentDisplayName,
    agentQueriesEnabled,
    autoGenerateHighlights,
    briefingSessions.profiles,
    demoModeActive,
    fullModelCatalog,
    generateBriefing,
    announceBriefingOutcome,
    hasActiveBriefingSession,
    workspaceView,
    openBriefingConversation,
    preflight,
    saveBriefingModelSettings,
    selectHudPeer,
    voiceMode,
  ])

  const startBriefing = useCallback(async (draft: BriefingSetupDraft): Promise<void> => {
    if (briefingOperationRef.current) throw new Error('A briefing is already being prepared.')
    briefingOperationRef.current = true
    try {
      await performBriefingGeneration(draft)
    } finally {
      briefingOperationRef.current = false
    }
  }, [performBriefingGeneration])

  const repeatLastBriefing = useCallback(async (): Promise<void> => {
    if (hasActiveBriefingSession) throw new Error('A briefing is already running.')
    const latest = await refreshLatestBriefingSession()
    if (!latest) throw new Error('No saved briefing history is available to repeat.')
    const profileId = latest.configuration.profile.id
    if (demoModeActive) {
      if (latest.configuration.execution_kind !== 'demo') throw new Error('Model-backed sessions cannot be repeated in DEMO_MODE.')
      if (profileId === 'deep') throw new Error('Deep is unavailable in DEMO_MODE.')
      await startBriefing({
        profileId,
        modelId: 'demo/daily-fixture',
        cloudEffort: null,
        localReasoningMode: null,
      })
      return
    }
    if (latest.configuration.execution_kind !== 'model') throw new Error('This saved fixture is available only in DEMO_MODE.')
    if (!agentQueriesEnabled) throw new Error(`Briefings are disabled in ${agentDisplayName} settings.`)
    const savedModel = latest.configuration.model
    const model = fullModelCatalog.find((entry) => entry.model_id === savedModel.model_id)
    if (!model || model.credentials_configured === false || model.status === 'disabled' || !['available', 'configured', 'verified', 'unknown', undefined].includes(model.status) || model.runtime !== savedModel.runtime) {
      throw new Error('The model used by this briefing is not currently available.')
    }
    if (model.runtime === 'cloud') {
      const options = model.reasoning_options ?? []
      if ((savedModel.reasoning === null && options.length > 0) || (savedModel.reasoning !== null && !options.includes(savedModel.reasoning as CloudEffort))) {
        throw new Error('The saved cloud reasoning effort is no longer supported by this model.')
      }
      if (savedModel.local_reasoning_mode !== null) throw new Error('The saved model configuration does not match the current cloud model.')
      await startBriefing({ profileId, modelId: model.model_id, cloudEffort: savedModel.reasoning as CloudEffort | null, localReasoningMode: null })
      return
    }
    const modes = model.reasoning_modes ?? (model.default_reasoning_mode ? [model.default_reasoning_mode] : [])
    if (!savedModel.local_reasoning_mode || !modes.includes(savedModel.local_reasoning_mode as LocalReasoningMode) || savedModel.reasoning !== null) {
      throw new Error('The saved local reasoning mode is no longer supported by this model.')
    }
    await startBriefing({ profileId, modelId: model.model_id, cloudEffort: null, localReasoningMode: savedModel.local_reasoning_mode as LocalReasoningMode })
  }, [agentDisplayName, agentQueriesEnabled, demoModeActive, fullModelCatalog, hasActiveBriefingSession, refreshLatestBriefingSession, startBriefing])

  const handleCollectOverviewTelemetry = useCallback((): void => {
    setIsLaunch(false)
    selectHudPeer('overview')
    void handleCollectTelemetry()
  }, [handleCollectTelemetry, selectHudPeer])

  const handleCollectBriefingTelemetry = useCallback((): void => {
    setBriefingTelemetryCollectionError(null)
    void handleCollectTelemetry(
      () => setBriefingTelemetryCollectionState('collecting'),
      (outcome) => {
        if (outcome.kind === 'success') {
          setBriefingTelemetryCollectionState(hasUsableTelemetry(outcome.snapshot) ? 'idle' : 'no-data')
          setBriefingTelemetryCollectionError(null)
        } else if (outcome.kind === 'failure' || outcome.kind === 'conflict') {
          setBriefingTelemetryCollectionState('error')
          setBriefingTelemetryCollectionError(outcome.error)
        } else {
          setBriefingTelemetryCollectionState('idle')
          setBriefingTelemetryCollectionError(null)
        }
      },
    ).then((started) => {
      if (!started) setBriefingTelemetryCollectionState('idle')
    })
  }, [handleCollectTelemetry])

  const handleSelectWorkspace = useCallback((peer: WorkspacePeer): void => {
    navigateWorkspace(peer)
  }, [navigateWorkspace])

  const briefingControlsBusy = preflight.isChecking || preflight.dialogOpen || briefingSessions.isGenerating
  const canGenerateBriefing = Boolean(agentQueriesEnabled || demoModeActive)
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
      collectionStarted,
      isRefreshing: isRefreshingAll,
      hasSnapshot,
      briefingStatus,
      briefingStep: activeStep,
    }
    return {
      reminders: resolveTelemetryAttentionTier('reminders', options),
      weather: resolveTelemetryAttentionTier('weather', options),
      news: resolveTelemetryAttentionTier('news', options),
      events: resolveTelemetryAttentionTier('events', options),
      market: resolveTelemetryAttentionTier('market', options),
      email: resolveTelemetryAttentionTier('email', options),
      insights: resolveTelemetryAttentionTier('insights', options),
    }
  }, [collectionStarted, isRefreshingAll, hasSnapshot, briefingStatus, activeStep])

  const attentionStagger = useMemo(
    () => ({
      reminders: resolveAttentionStaggerMs('reminders'),
      weather: resolveAttentionStaggerMs('weather'),
      news: resolveAttentionStaggerMs('news'),
      events: resolveAttentionStaggerMs('events'),
      market: resolveAttentionStaggerMs('market'),
      email: resolveAttentionStaggerMs('email'),
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
    const session = briefingSessions.activeSession
    if (!briefingWorkspaceOpen || !session || briefingSessions.selectedSessionId !== session.id || session.run_status !== 'completed' || !session.artifact) return
    if (completedBriefingHistoryRef.current.has(session.id) && assistantConversationId === session.conversation_id) return
    if (briefingOpeningSessionsRef.current.has(session.id)) return
    const sequence = ++briefingOpenSequenceRef.current
    briefingOpeningSessionsRef.current.set(session.id, sequence)
    void openBriefingConversation(session.conversation_id, session.id, sequence).finally(() => {
      if (briefingOpeningSessionsRef.current.get(session.id) === sequence) briefingOpeningSessionsRef.current.delete(session.id)
    })
  }, [assistantConversationId, briefingWorkspaceOpen, briefingSessions.activeSession, briefingSessions.selectedSessionId, openBriefingConversation])

  const handleCancelBriefingSession = useCallback((sessionId: string): void => {
    void cancelBriefingSession(sessionId).catch(() => undefined)
  }, [cancelBriefingSession])

  const logoStatus = briefingStatus !== 'idle'
    ? briefingStatus
    : isRefreshingAll
      ? 'loading'
      : hasCollectedTelemetry
        ? 'success'
        : 'idle'
  const isOverviewCentered = !isLaunch && workspace === 'overview' &&
    (overviewState === 'center' || overviewState === 'error' || overviewState === 'no-data')

  const cortexLogoProps: Omit<ApexLogoProps, 'className'> = {
    status: logoStatus,
    activity: logoActivity,
    isSpeaking,
    reminderPulseCount,
    isCortexQuerying,
    isTelemetryCollecting,
    hasCollectedTelemetry,
    outerShellActivity,
  }

  const f1ScheduleTelemetryText = f1Module?.display_text?.trim() ?? ''
  const emailInfo = resolveEmailTelemetry(emailModule)
  const newsInfo = resolveNewsTelemetry(newsModule)
  const calendarInfo = resolveCalendarTelemetry(calendarModule)
  const footballInfo = resolveFootballTelemetry(footballModule)

  const eventsCompactValue = hasSnapshot
    ? [
        calendarInfo.totalCount > 0 ? `${calendarInfo.totalCount} calendar` : null,
        footballInfo.fixtures.length > 0 ? `${footballInfo.fixtures.length} football` : null,
      ].filter((value): value is string => value !== null).join(' · ') || 'No events'
    : null
  const emailCompactValue = emailInfo.state === 'available' && emailInfo.count !== null ? `${emailInfo.count} unread` : null
  const newsCompactValue = newsInfo.state === 'available' ? `${newsInfo.items.length} headlines` : null
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
    let runtimePatch: { local?: { last_model: string; reasoning_mode?: LocalReasoningMode }; cloud?: { last_model: string; effort: CloudEffort } }
    if (entry?.runtime === 'local') {
      const supportedModes = entry.reasoning_modes ?? []
      if (supportedModes.length === 0) {
        runtimePatch = { local: { last_model: model } }
      } else {
        const nextMode = supportedModes.includes(localReasoningMode)
          ? localReasoningMode
          : entry.default_reasoning_mode ?? supportedModes[0]
        if (nextMode !== localReasoningMode) setLocalReasoningMode(nextMode)
        runtimePatch = { local: { last_model: model, reasoning_mode: nextMode } }
      }
    } else {
      runtimePatch = { cloud: { last_model: model, effort: nextEffort } }
    }
    void persistAgentSettings({
      selected_model: model, ...runtimePatch,
    }, { refreshToolCatalog: true })
  }, [cloudEffort, fullModelCatalog, localReasoningMode, persistAgentSettings])

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
      return 'This linked review could not be reached. Refresh Reports and try again.'
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
    session: briefingSessions.activeSession,
    selectedSession: briefingSessions.sessions.find((session) => session.id === briefingSessions.selectedSessionId) ?? null,
    isGenerating: briefingSessions.isGenerating,
  })
  const briefingEvidence = useMemo(() => ({
    evidenceById: briefingSessions.evidenceById,
    loadingIds: briefingSessions.evidenceLoadingIds,
    errors: briefingSessions.evidenceErrors,
    onLoadEvidence: briefingSessions.loadEvidence,
  }), [briefingSessions.evidenceById, briefingSessions.evidenceErrors, briefingSessions.evidenceLoadingIds, briefingSessions.loadEvidence])
  const hudIdentity: HudIdentityProps = {
    logoProps: cortexLogoProps,
    glyphProps: {
      status: logoStatus,
      activity: logoActivity,
      isSpeaking,
      activeTtsEngine: resolvedTtsEngine,
      systemLoadThrottled: resolvedSystemThrottled,
      isCortexQuerying,
      cortexActivityLabel: assistantActivityLabel,
      isLocalModelLoading,
      loadingDisplayName,
      isTelemetryCollecting,
    },
  }
  const hudTelemetry: HudTelemetryData = {
    hasSnapshot,
    isRefreshingAll,
    isRefreshingAnyConnector: telemetry.refreshingConnectors.size > 0,
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
    email: {
      state: emailInfo.state,
      ledState: emailLedState,
      statusMessage: emailStatusMessage,
      compactValue: emailCompactValue,
      count: emailInfo.count,
      items: emailInfo.items,
      refreshing: emailRefreshing,
    },
    news: {
      state: newsInfo.state,
      ledState: newsLedState,
      statusMessage: newsStatusMessage,
      compactValue: newsCompactValue,
      items: newsInfo.items,
      refreshing: newsRefreshing,
    },
    reminders: {
      ledState: resolveModuleLedState(remindersModule, remindersRefreshing),
      statusMessage: remindersStatusMessage,
      compactValue: remindersCompactValue,
      items: activeReminders,
      loadState: remindersLoadState,
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
      <CelestialBackground
        isLaunch={isLaunch}
        workspace={workspace}
        atmosphereGlowColor={atmosphereGlowColor}
      />

      <div className={`hud-main-shell relative z-[var(--z-bento-hud)] flex h-full min-h-0 flex-1 flex-col overflow-visible xl:overflow-hidden ${isOverviewCentered ? 'hud-main-shell--overview-center' : ''}`}>
        {!isLaunch ? <header className="hud-header hud-header--workspace relative pointer-events-none mb-4 flex h-20 w-full shrink-0 select-none flex-nowrap items-center">
          <SystemDiagnostics
            diagnostics={diagnostics}
            diagnosticsStatus={diagnosticsStatus}
            failedConnectors={telemetry.snapshot?.failed_connectors ?? []}
            connectorHealth={telemetry.snapshot?.connector_health ?? []}
            isCheckingConnectors={isRefreshingAll}
            refreshingConnectors={telemetry.refreshingConnectors}
            onRefreshConnectors={handleRefreshAll}
            demoModeActive={demoModeActive}
            devModeActive={devModeActive}
            onOpenSettings={() => setIsSettingsOpen(true)}
            settingsButtonRef={settingsButtonRef}
            onReturnToLaunch={() => setIsLaunch(true)}
            workspaceNavigation={<WorkspaceTabs current={workspace} onSelect={handleSelectWorkspace} />}
          />
        </header> : null}

        <SettingsPanel
          open={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          restoreFocusRef={settingsButtonRef}
          briefingRunning={isBriefingRunning}
          briefingStep={activeStep}
          isSpeaking={isSpeaking}
          isCortexQuerying={isCortexQuerying}
          modelCatalog={fullModelCatalog}
          cortexAgentHydrated={cortexAgentHydrated}
          failedConnectors={telemetry.snapshot?.failed_connectors ?? []}
          hasTelemetryEvidence={hasSnapshot}
          onApplied={handleSettingsPanelApplied}
          mcpRuntime={mcpRuntime}
        />

        <ApexAssistantRuntime
          key={`${demoModeActive ? 'demo' : devModeActive && sandboxMode ? 'sandbox' : 'production'}`}
          config={{
            agent: effectiveWorkspaceAgent,
            effort: effectiveWorkspaceRuntime === 'cloud' ? (usesSharedAgentTurn ? agentTurnOverrides.effort : cloudEffort) : null,
            modelId: effectiveWorkspaceModel,
            contextWindow: effectiveWorkspaceRuntime === 'local' ? (usesSharedAgentTurn ? agentTurnOverrides.contextWindow : localContextWindow) : null,
            localReasoningMode: effectiveWorkspaceRuntime === 'local' ? (usesSharedAgentTurn ? agentTurnOverrides.localReasoningMode : localReasoningMode) : null,
            selectedToolNames: toolCatalogState.selectedToolNames,
            toolProfileId: toolCatalogState.activeToolProfileId,
            snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
          }}
          beforeRun={runAssistantPreflight}
          runtimeRef={assistantRuntimeRef}
          onConversationChange={handleAssistantConversationChange}
          onRunningChange={handleAssistantRunningChange}
          onActivityChange={setAssistantActivityLabel}
          toolLabels={toolCatalogState.catalog?.tools ?? []}
          onResponseChange={handleAssistantResponseChange}
        >
        {isLaunch ? <LaunchView
          logoProps={cortexLogoProps}
          current={null}
          onSelect={handleSelectWorkspace}
          onOpenSettings={() => setIsSettingsOpen(true)}
          settingsButtonRef={settingsButtonRef}
          mode={demoModeActive ? 'DEMO' : devModeActive ? 'DEVELOPER' : null}
        /> : workspace === 'overview' || workspace === 'briefing' ? (
          <HudWorkspace
            view={workspaceView.view}
            briefingPhase={briefingPhase}
            identity={hudIdentity}
            telemetry={hudTelemetry}
            overviewActions={{
              onCollectTelemetry: handleCollectOverviewTelemetry,
              disabled: preflight.isChecking,
            }}
            overviewState={overviewState}
            overviewError={overviewError}
            onRefreshAll={handleRefreshAll}
            briefingControls={{
              agentDisplayName,
              profiles: briefingSessions.profiles,
              profileId: workspaceView.profileId,
              onProfileChange: workspaceView.setProfileId,
              selectedModelId: selectedModel,
              cloudEffort,
              localReasoningMode,
              modelCatalog: fullModelCatalog,
              canGenerate: canGenerateBriefing,
              busy: briefingControlsBusy,
              hasActiveSession: briefingSessions.hasActiveSession,
              isGenerating: briefingSessions.isGenerating,
              onGenerate: startBriefing,
              onRepeat: repeatLastBriefing,
              autoOpenSetup: briefingSetupAutoOpen,
              onAutoOpenSetupConsumed: () => setBriefingSetupAutoOpen(false),
              demoModeActive,
              onCancel: handleCancelBriefingSession,
              sessions: briefingSessions.sessions,
              selectedSessionId: briefingSessions.selectedSessionId,
              isLoadingSessions: briefingSessions.isLoadingSessions,
              onOpenSession: (sessionId) => void handleOpenBriefingSession(sessionId),
              activeSession: briefingSessions.activeSession,
              latestSession: briefingSessions.latestSession,
              latestError: briefingSessions.latestError,
              isLoadingLatestSession: briefingSessions.isLoadingLatestSession,
              error: briefingSessions.error,
              activeLocalModel,
              loadingLocalModel,
              localLifecycleBusy,
              onUnloadLocalModel: unloadLocalModel,
              speechControl: selectedCompletedBriefing ? <BriefingSpeechControl
                {...briefingSpeech}
                voiceMode={voiceMode}
                agentDisplayName={agentDisplayName}
                configuredTtsEngine={voiceEngine}
              /> : null,
              autoGenerateHighlights,
              onAutoGenerateHighlightsChange: handleAutoGenerateHighlightsChange,
              voiceMode,
              configuredTtsEngine: voiceEngine,
            }}
            briefingConversation={{
              ready: briefingConversationReady === briefingSessions.activeSession?.conversation_id && assistantConversationId === briefingSessions.activeSession?.conversation_id,
              canFollowUp: Boolean(agentQueriesEnabled) && !demoModeActive,
              session: briefingSessions.activeSession,
              previewSections: briefingSessions.preview?.sessionId === briefingSessions.activeSession?.id ? briefingSessions.preview?.sections : undefined,
              isLoadingSession: briefingSessions.isLoadingSession,
              evidence: briefingEvidence,
              onMarkPresented: briefingSessions.markPresented,
              onOpenConversation: (conversationId) => void openBriefingConversation(conversationId),
              agentDisplayName,
              speech: briefingSpeech.speech,
              composer: {
                activeAgent: 'apex',
                activeAgentName: agentDisplayName,
                integrated: true,
                disabled: conversationHydrating || !toolCatalogState.selectionReady || demoModeActive,
                selectedModelId: selectedModel,
                onModelChange: handleModelChange,
                modelCatalog: fullModelCatalog,
                cloudEffort,
                onEffortChange: handleEffortChange,
                localReasoningMode,
                onLocalReasoningModeChange: handleLocalReasoningModeChange,
                tools: {
                  catalog: toolCatalogState.catalog,
                  selectedToolNames: toolCatalogState.selectedToolNames,
                  activeToolProfileId: toolCatalogState.activeToolProfileId,
                  onSelectionChange: toolCatalogState.setSelectedToolNames,
                  onProfileChange: toolCatalogState.applyToolProfile,
                  preflight: toolPreflightState.estimate,
                  preflightLoading: toolPreflightState.isLoading,
                  catalogError: toolCatalogState.error,
                  preflightError: toolPreflightState.error,
                  profileFeedback: toolProfileFeedback,
                  profileError: toolProfileError,
                  onSaveProfile: saveToolProfile,
                  onDuplicateProfile: duplicateToolProfile,
                  onRenameProfile: renameToolProfile,
                  onDeleteProfile: deleteToolProfile,
                  onRestoreProfile: restoreToolProfile,
                  onSetDefaultProfile: setDefaultToolProfile,
                },
              },
            }}
            briefingTelemetry={{
              hasUsableSnapshot: hasCollectedTelemetry,
              state: briefingTelemetryCollectionState,
              error: briefingTelemetryCollectionError,
              disabled: preflight.isChecking || preflight.dialogOpen,
              onCollect: handleCollectBriefingTelemetry,
            }}
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
            onVerifyCloudModel={verifyCloudModel}
            snapshotAttached={snapshotAttached}
            snapshotAvailable={telemetry.snapshot !== null}
            onSnapshotAttachedChange={setSnapshotAttached}
            personalContextEnabled={sharedAgentModelEntry?.runtime === 'local' ? localPersonalContextEnabled : cloudPersonalContextEnabled}
            onPersonalContextEnabledChange={(enabled) => persistAgentSettings(sharedAgentModelEntry?.runtime === 'local' ? { local: { personal_context_enabled: enabled } } : { cloud: { personal_context_enabled: enabled } })}
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
              effort: sharedAgentModelEntry?.runtime === 'cloud' ? cloudEffort : null,
              modelId: selectedModel,
              contextWindow: sharedAgentModelEntry?.runtime === 'local' ? localContextWindow : null,
              localReasoningMode: sharedAgentModelEntry?.runtime === 'local' ? localReasoningMode : null,
              selectedToolNames: toolCatalogState.selectedToolNames,
              toolProfileId: toolCatalogState.activeToolProfileId,
              snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
            }}
            onAssistantPreflight={runAssistantPreflight}
            linkedReviewId={linkedReviewId}
          />
        ) : (
          <ActivityReportsWorkspace
            reports={activityReports}
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
