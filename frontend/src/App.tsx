import {
  Calendar,
  CheckSquare,
  Clock,
  CloudSun,
  Mail,
  Newspaper,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react'

import { ApexLogo, type ApexLogoProps } from './components/ApexLogo'
import { CelestialBackground } from './components/CelestialBackground'
import { CortexWorkspace } from './components/CortexWorkspace'
import { ApexAssistantRuntime, type ApexAssistantRunConfig, type ApexAssistantRuntimeHandle } from './components/ApexAssistantRuntime'
import { BriefingDigest } from './components/BriefingDigest'
import { CalendarEventList } from './components/CalendarEventList'
import { FootballFixtureList } from './components/FootballFixtureList'
import { MarketTickerCard } from './components/MarketTickerCard'
import { PreflightDialog } from './components/PreflightDialog'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderQuickAdd } from './components/ReminderQuickAdd'
import { ReminderReviewDialog } from './components/ReminderReviewDialog'
import { ReminderTaskDialog } from './components/ReminderTaskDialog'
import { CompletedRemindersDialog } from './components/CompletedRemindersDialog'
import SettingsPanel from './components/SettingsPanel'
import { HomeCommandRail } from './components/HomeCommandRail'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VoiceSignalGlyph } from './components/VoiceSignalGlyph'
import { useApexData } from './hooks/useApexData'
import { useCortex } from './hooks/useCortex'
import { useActions } from './hooks/useActions'
import { useAppActivation } from './hooks/useAppActivation'
import { useBriefingPipeline } from './hooks/useBriefingPipeline'
import { useMarketData } from './hooks/useMarketData'
import { useMcpStatus } from './hooks/useMcpStatus'
import { usePreflight } from './hooks/usePreflight'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import { useTelemetrySnapshot } from './hooks/useTelemetrySnapshot'
import { useToolCatalog } from './hooks/useToolCatalog'
import { useToolPreflight } from './hooks/useToolPreflight'
import { useVoiceDelivery } from './hooks/useVoiceDelivery'
import { API_ENDPOINTS } from './lib/api'
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
  resolveBriefingModeAvailability,
  resolveHomeQueryOverrides,
} from './lib/agents'
import type {
  AgentKey,
  BriefingTargetStatus,
  CloudEffort,
  HostedTool,
  LocalReasoningMode,
} from './types/telemetry'
import type {
  BriefingMode,
  CloudHostedToolsSettings,
  SettingsResponse,
  VoiceMode,
} from './types/settings'

function sameToolNames(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((name) => right.includes(name))
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

const VALID_BRIEFING_MODES: readonly BriefingMode[] = [
  'flash',
  'focused',
  'structured',
]

function isBriefingMode(value: string): value is BriefingMode {
  return (VALID_BRIEFING_MODES as readonly string[]).includes(value)
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
  const [briefingMode, setBriefingMode] = useState<BriefingMode>('flash')
  const briefingModeSelectionTouchedRef = useRef(false)
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('automatic')
  const [workspace, setWorkspace] = useState<'home' | 'cortex'>('home')
  const [selectedModel, setSelectedModel] = useState('deepseek/deepseek-v4-flash-0731')
  const [sandboxMode, setSandboxMode] = useState(false)
  const [hostedTools, setHostedTools] = useState<CloudHostedToolsSettings>({
    google_search: true,
    google_maps: true,
    x_search: true,
  })
  const [snapshotAttached, setSnapshotAttached] = useState(true)
  const [cloudPersonalContextEnabled, setCloudPersonalContextEnabled] = useState(false)
  const [localPersonalContextEnabled, setLocalPersonalContextEnabled] = useState(false)
  const [localContextWindow, setLocalContextWindow] = useState(16384)
  const [localReasoningMode, setLocalReasoningMode] = useState<LocalReasoningMode>('none')
  const [draftPrompt, setDraftPrompt] = useState('')
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
  const [marketPollKey, setMarketPollKey] = useState(0)
  const [briefingTargets, setBriefingTargets] = useState<BriefingTargetStatus[]>([])
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
    briefingDefaultMode,
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
  const actions = useActions(
    workspace === 'cortex' && !demoModeActive,
  )
  const { data: marketData, isLoading: isMarketLoading } = useMarketData(
    marketEnabled,
    marketPollKey,
  )

  const { activated, activate } = useAppActivation()
  const preflight = usePreflight()
  const telemetry = useTelemetrySnapshot()
  const briefing = useBriefingPipeline()
  const voiceDelivery = useVoiceDelivery(
    briefing.briefing,
    briefing.status,
    briefing.isSpeaking,
  )

  const {
    agentsStatus,
    agentsStatusHydrated,
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

  const fullModelCatalog = useMemo(
    () => agentsStatus[0]?.model_catalog ?? [],
    [agentsStatus],
  )

  const homeSelectedEntry = useMemo(
    () => fullModelCatalog.find((entry) => entry.model_id === selectedModel) ?? fullModelCatalog[0],
    [fullModelCatalog, selectedModel],
  )
  const homeOverrides = useMemo(
    () => resolveHomeQueryOverrides(homeSelectedEntry),
    [homeSelectedEntry],
  )

  const effectiveWorkspaceAgent = workspace === 'home' ? homeOverrides.agent : activeAgent
  const effectiveWorkspaceModel = workspace === 'home' ? homeOverrides.modelId : selectedModel
  const effectiveWorkspaceRuntime = (workspace === 'home' ? homeSelectedEntry : fullModelCatalog.find(
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
    modelId: workspace === 'home' ? homeOverrides.modelId : selectedModel,
    effort: workspace === 'home' ? homeOverrides.effort : (homeSelectedEntry?.runtime === 'cloud' ? cloudEffort : null),
    contextWindow: workspace === 'home' ? homeOverrides.contextWindow : null,
    localReasoningMode: workspace === 'home' ? homeOverrides.localReasoningMode : null,
    selectedToolNames: toolCatalogState.selectedToolNames,
    toolProfileId: toolCatalogState.activeToolProfileId,
    prompt: draftPrompt,
    conversationId: assistantConversationId,
    snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
    enabled: Boolean(
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
    if (
      !briefingModeSelectionTouchedRef.current &&
      briefingDefaultMode &&
      isBriefingMode(briefingDefaultMode)
    ) {
      setBriefingMode(briefingDefaultMode)
    }
    if (bootVoiceMode && isVoiceMode(bootVoiceMode)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Mirrors asynchronous boot configuration into local controls.
      setVoiceMode(bootVoiceMode)
    }
  }, [bootVoiceMode, briefingDefaultMode])

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
      if (!briefingModeSelectionTouchedRef.current) {
        setBriefingMode(response.settings.briefing.default_mode)
      }
      setVoiceMode(response.settings.voice.mode)
    },
    [applyBootSettings],
  )

  const handleSettingsPanelApplied = useCallback(
    async (response: SettingsResponse) => {
      handleSettingsApplied(response)
      setMarketPollKey((key) => key + 1)
      await refreshAgentsStatus()
      await toolCatalogState.refreshCatalog()
    },
    [handleSettingsApplied, refreshAgentsStatus, toolCatalogState],
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
        const briefing = settingsValues.briefing
        if (
          !briefingModeSelectionTouchedRef.current &&
          briefing &&
          typeof briefing === 'object'
        ) {
          const mode = (briefing as Record<string, unknown>).default_mode
          if (typeof mode === 'string' && isBriefingMode(mode)) {
            setBriefingMode(mode)
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

  const loadingLocalAgent = useMemo(
    () => agentsStatus.find((agent) => agent.loading) ?? null,
    [agentsStatus],
  )
  const activeLocalModel = useMemo(
    () =>
      agentsStatus.find(
        (agent) => agent.active,
      ) ?? null,
    [agentsStatus],
  )
  const isLocalModelLoading =
    loadingLocalAgent !== null ||
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
  const isDormant = !activated
  const wingTransition =
    'transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)]'
  const wingHeightClass = 'xl:h-full'
  const leftWingDormantClasses = 'opacity-0 -translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const leftWingActiveClasses = 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
  const rightWingDormantClasses = 'opacity-0 translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const rightWingActiveClasses = 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
  const centerColumnDormantClasses = 'grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] xl:max-w-full xl:flex-1'
  const centerColumnActiveClasses = 'grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] pt-0 xl:max-w-[33.33%] xl:flex-1 xl:min-h-0 min-w-0'

  // The logo is always visible and the insights panel stays mounted while the
  // Home telemetry columns transition around it.
  const showDigest = !isDormant
  const digestWrapperClass = [
    'hud-digest-wrapper transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu min-h-0 w-full min-w-0 max-w-full',
    showDigest
      ? 'max-h-[220px] xl:max-h-[240px] opacity-100 mb-3 xl:mb-4 overflow-hidden'
      : 'max-h-0 opacity-0 mb-0 overflow-hidden pointer-events-none',
  ].join(' ')

  const logoShellClass = 'hud-logo-shell flex min-h-0 w-full items-center justify-center py-4 xl:py-0'

  const largeLogoWrapperClass = 'hud-logo-wrapper relative flex h-full min-h-0 flex-col items-center justify-center transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu opacity-100 scale-100'

  const logoSizeClass = 'hud-logo-mark h-48 w-auto sm:h-56 xl:h-64'

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
    void telemetry.refreshAll({ force: false })
    if (voiceMode === 'automatic') {
      void fetch(API_ENDPOINTS.voiceSpeak, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: 'APEX online. Ready for operations.' }),
      }).catch(() => {
        // Activation voice cue is best-effort; ignore delivery failures.
      })
    }
  }, [preflight, activate, telemetry, voiceMode])

  const handleStartWithBriefing = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('activate_with_briefing', {
      briefing_mode: briefingMode,
    })
    if (resolution !== 'proceed') {
      return
    }

    activate()
    await briefing.triggerSynthesis(briefingMode)
    void telemetry.loadLatest()
  }, [preflight, briefingMode, activate, briefing, telemetry])

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

      void handleStartApex()
    }

    window.addEventListener('keydown', handleGlobalEnter)
    return () => {
      window.removeEventListener('keydown', handleGlobalEnter)
    }
  }, [activated, handleStartApex, preflight.dialogOpen, preflight.isChecking])

  useEffect(() => {
    let ignore = false
    void fetch(API_ENDPOINTS.briefingTargets)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && Array.isArray(data)) {
          setBriefingTargets(data as BriefingTargetStatus[])
        }
      })
      .catch(() => {})
    return () => {
      ignore = true
    }
  }, [agentsStatus])

  const hasSnapshot = telemetry.snapshot !== null
  const briefingControlsBusy =
    preflight.isChecking || preflight.dialogOpen || isBriefingRunning || isTelemetryCollecting
  const briefingModeAvailable = useMemo(() => {
    const availability = resolveBriefingModeAvailability(
      briefingMode,
      briefingTargets,
    )
    return ['available', 'configured', 'verified'].includes(availability.status)
  }, [briefingMode, briefingTargets])
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

  const weatherModule = telemetry.snapshot?.modules.weather
  const newsModule = telemetry.snapshot?.modules.news
  const emailModule = telemetry.snapshot?.modules.email
  const calendarModule = telemetry.snapshot?.modules.calendar
  const f1Module = telemetry.snapshot?.modules.f1
  const footballModule = telemetry.snapshot?.modules.football
  const remindersModule = telemetry.snapshot?.modules.reminders

  const wingGapClass = 'gap-4'
  const weatherPanelLayoutClass = 'xl:flex-[0.5_1_0] xl:min-h-0'
  const eventsPanelLayoutClass = 'xl:flex-[1.5_1_0] xl:min-h-0'
  const marketPanelLayoutClass = 'xl:flex-[1_1_0]'
  const rightTelemetryPanelClass = 'flex-none xl:flex-1 xl:min-h-0'

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

  const primaryTemperatureF = weatherInfo.temperatureF

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

  const handleGenerateBriefing = useCallback(async (): Promise<void> => {
    const snapshotId = telemetry.snapshot?.snapshot_id
    if (!snapshotId) {
      return
    }
    const resolution = await preflight.requestOperation('generate_briefing', {
      briefing_mode: briefingMode,
    })
    if (resolution !== 'proceed') {
      return
    }
    await briefing.generateFromSnapshot(snapshotId, briefingMode)
  }, [preflight, briefingMode, briefing, telemetry.snapshot?.snapshot_id])

  const handleRefreshAllAndGenerate = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('generate_briefing', {
      briefing_mode: briefingMode,
      force: true,
    })
    if (resolution !== 'proceed') {
      return
    }
    const snapshot = await telemetry.refreshAll({ force: true })
    if (!snapshot) {
      return
    }
    await briefing.generateFromSnapshot(snapshot.snapshot_id, briefingMode)
  }, [preflight, briefingMode, briefing, telemetry])

  const handleSpeakBriefing = useCallback((): void => {
    const text = briefing.briefing.trim()
    if (!text || voiceMode === 'off') {
      return
    }
    void voiceDelivery.speak(text)
  }, [briefing.briefing, voiceMode, voiceDelivery])

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

  const synthesisInsights = briefing.insights

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

  const persistBriefingMode = useCallback(async (mode: BriefingMode): Promise<void> => {
    try {
      await fetch(API_ENDPOINTS.settings, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ briefing: { default_mode: mode } }),
      })
    } catch {
      // Keep the selected mode usable for this session if persistence is unavailable.
    }
  }, [])

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

  const handleBriefingModeChange = useCallback((mode: BriefingMode): void => {
    briefingModeSelectionTouchedRef.current = true
    setBriefingMode(mode)
    void persistBriefingMode(mode)
  }, [persistBriefingMode])

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

  const handleHomeSubmit = useCallback(async (
    query: string,
    selectedToolNames: string[],
    toolProfileId: string | null,
  ): Promise<boolean> => {
    const selectedEntry = fullModelCatalog.find((entry) => entry.model_id === selectedModel)
      ?? fullModelCatalog[0]
    const overrides = resolveHomeQueryOverrides(selectedEntry)
    const accepted = await assistantRuntimeRef.current?.submitPrompt(query, {
      agent: overrides.agent,
      modelId: overrides.modelId,
      effort: overrides.effort,
      contextWindow: overrides.contextWindow,
      localReasoningMode: overrides.localReasoningMode,
      selectedToolNames,
      toolProfileId,
    }, { startNewThread: true }) ?? false
    if (accepted) {
      setWorkspace('cortex')
    }
    return accepted
  }, [fullModelCatalog, selectedModel])

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
            <button type="button" onClick={() => setWorkspace('home')} aria-pressed={workspace === 'home'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'home' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'text-zinc-500 hover:text-zinc-200'}`}>Home</button>
            <button type="button" onClick={() => setWorkspace('cortex')} aria-pressed={workspace === 'cortex'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'cortex' ? 'bg-[#7E22CE]/25 text-[#D8B4FE]' : 'text-zinc-500 hover:text-zinc-200'}`}>Cortex</button>
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
          agentsStatus={agentsStatus}
          agentsStatusHydrated={agentsStatusHydrated}
          failedConnectors={briefing.failedConnectors}
          hasBriefingEvidence={briefing.status === 'success' || briefing.status === 'error'}
          onApplied={handleSettingsPanelApplied}
          mcpRuntime={mcpRuntime}
        />

        <ApexAssistantRuntime
          key={`${demoModeActive ? 'demo' : devModeActive && sandboxMode ? 'sandbox' : 'production'}`}
          config={{
            agent: activeAgent,
            effort: homeSelectedEntry?.runtime === 'cloud' ? cloudEffort : null,
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
          <>
        <div className="hud-body-layout flex w-full flex-col gap-4 overflow-visible xl:h-full xl:min-h-0 xl:flex-1 xl:flex-row xl:overflow-hidden xl:gap-6">
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`hud-wing-column order-2 flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} xl:order-1 xl:min-h-0 xl:flex xl:flex-col ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <div className={`flex min-h-0 flex-col ${wingGapClass} xl:flex xl:flex-1`}>
                <TelemetryCard
                  title="Weather"
                  icon={CloudSun}
                  primaryTemperatureF={primaryTemperatureF}
                  apparentTemperatureF={weatherInfo.apparentTempF}
                  tempMaxF={weatherInfo.tempMaxF}
                  tempMinF={weatherInfo.tempMinF}
                  windSpeedMph={weatherInfo.windSpeedMph}
                  weatherTimeline={weatherInfo.timeline}
                  weatherCondition={weatherInfo.condition}
                  ledState={weatherLedState}
                  onRefresh={() => handleRefreshConnector('weather')}
                  refreshDisabled={isRefreshingAll}
                  statusMessage={weatherStatusMessage}
                  compactValue={weatherBody}
                  headerAction={weatherModule?.status === 'healthy' ? (
                    <span
                      className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-x-1 text-[9px] leading-tight text-[color:var(--hud-muted-text)]"
                      aria-label="Weather by Open-Meteo. Location by GeoNames. Licensed under CC BY 4.0. Adapted by APEX."
                    >
                      <span>Weather by</span>
                      <a
                        href="https://open-meteo.com/"
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-[color:var(--hud-text)]"
                      >
                        Open-Meteo
                      </a>
                      <span>· Location by</span>
                      <a
                        href="https://www.geonames.org/"
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-[color:var(--hud-text)]"
                      >
                        GeoNames
                      </a>
                      <span>·</span>
                      <a
                        href="https://creativecommons.org/licenses/by/4.0/"
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-[color:var(--hud-text)]"
                      >
                        CC BY 4.0
                      </a>
                      <span>· adapted by APEX</span>
                    </span>
                  ) : undefined}
                  attentionTier={attentionTiers.weather}
                  attentionStaggerMs={attentionStagger.weather}
                  className={`min-h-0 ${weatherPanelLayoutClass}`}
                >
                  {primaryTemperatureF == null ? (
                    <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                      {weatherBody}
                    </p>
                  ) : null}
                </TelemetryCard>

                <TelemetryCard
                  title="Events"
                  icon={Calendar}
                  f1TelemetryText={f1ScheduleTelemetryText}
                  ledState={calendarLedState}
                  refreshActions={[
                    { label: 'Calendar', onRefresh: () => handleRefreshConnector('calendar'), disabled: isRefreshingAll, loading: calendarRefreshing },
                    { label: 'F1', onRefresh: () => handleRefreshConnector('f1'), disabled: isRefreshingAll, loading: f1Refreshing },
                    { label: 'Football', onRefresh: () => handleRefreshConnector('football'), disabled: isRefreshingAll, loading: footballRefreshing },
                  ]}
                  statusMessage={eventsStatusMessage}
                  compactValue={eventsCompactValue}
                  attentionTier={attentionTiers.events}
                  attentionStaggerMs={attentionStagger.events}
                  className={`min-h-0 ${eventsPanelLayoutClass}`}
                >
                  {calendarRefreshing && !hasSnapshot ? (
                    <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                      Loading schedule…
                    </p>
                  ) : (
                    <>
                      <CalendarEventList
                        telemetry={calendarInfo}
                        hasSnapshot={hasSnapshot}
                      />
                      <FootballFixtureList telemetry={footballInfo} module={footballModule} hasSnapshot={hasSnapshot} />
                    </>
                  )}
                </TelemetryCard>

                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
                      enabled={marketEnabled}
                      attentionTier={attentionTiers.market}
                      attentionStaggerMs={attentionStagger.market}
                      className={`min-h-0 w-full ${marketPanelLayoutClass}`}
                    />
              </div>
            </div>

            {/* COLUMN 2: CENTER REACTOR */}
            <div
              className={`hud-center-column order-1 relative z-[var(--z-core-logo)] min-w-0 items-stretch justify-items-center gap-4 xl:order-2 xl:gap-6 ${wingTransition} ${isDormant ? centerColumnDormantClasses : centerColumnActiveClasses}`}
            >
              {/* Ambient Logo Glow Projector */}
              <div
                className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-12 h-[380px] w-[380px] rounded-full blur-[120px] opacity-10 mix-blend-screen"
                style={{ background: 'rgba(var(--atmosphere-glow-color), 0.15)' }}
                aria-hidden
              />
              <div className={`shrink-0 flex flex-col ${digestWrapperClass}`}>
                <BriefingDigest
                  insights={synthesisInsights}
                  briefingText={briefing.briefing}
                  status={briefing.status}
                  activated={activated}
                  isLoading={briefing.status === 'loading'}
                  onSpeakBriefing={handleSpeakBriefing}
                  speakDisabled={isSpeaking}
                  showSpeakAction={voiceMode !== 'off'}
                  speechError={voiceDelivery.error}
                  deliveryLabel={
                    voiceDelivery.lastManualEngine
                      ? `Last manual delivery: ${voiceDelivery.lastManualEngine}`
                      : null
                  }
                  synthesisLabel={
                    briefing.synthesisProvider
                      ? [briefing.synthesisProvider, briefing.synthesisModelId]
                          .filter(Boolean)
                          .join(' / ')
                      : null
                  }
                  fallbackReason={briefing.synthesisFallbackReason}
                  attentionTier={attentionTiers.insights}
                  attentionStaggerMs={attentionStagger.insights}
                  className="w-full h-full min-h-0"
                />
              </div>

              <div className={`${logoShellClass} ${largeLogoWrapperClass}`}>
                <div className="relative flex flex-col items-center">
                  <div
                    className={`filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)] ${isDormant ? 'scale-115 xl:scale-125' : 'scale-100'}`}
                  >
                    <ApexLogo
                      step={activeStep}
                      status={logoStatus}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      isCortexQuerying={isCortexQuerying}
                      isTelemetryCollecting={isTelemetryCollecting}
                      outerShellActivity={outerShellActivity}
                      className={logoSizeClass}
                    />
                  </div>
                  <div
                    className={`flex flex-col items-center whitespace-nowrap transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                      isDormant ? 'mt-7 xl:mt-9' : 'mt-2'
                    }`}
                  >
                    <VoiceSignalGlyph
                      step={activeStep}
                      status={logoStatus}
                      isSpeaking={isSpeaking}
                      activeTtsEngine={resolvedTtsEngine}
                      systemLoadThrottled={resolvedSystemThrottled}
                      isCortexQuerying={isCortexQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      loadingDisplayName={loadingDisplayName}
                      isTelemetryCollecting={isTelemetryCollecting}
                    />
                  </div>
                </div>
              </div>
              <div className="flex w-full min-w-0 max-w-full flex-col items-center">
                <HomeCommandRail
                  activated={activated}
                  agentQueriesEnabled={Boolean(agentQueriesEnabled)}
                  selectedModelId={selectedModel}
                  onModelChange={handleHomeModelChange}
                  modelCatalog={fullModelCatalog}
                  agentsStatus={agentsStatus}
                  isCortexQuerying={isCortexQuerying}
                  onAgentSubmit={handleHomeSubmit}
                  toolCatalog={toolCatalogState.catalog}
                  selectedToolNames={toolCatalogState.selectedToolNames}
                  activeToolProfileId={toolCatalogState.activeToolProfileId}
                  selectionReady={toolCatalogState.selectionReady}
                  submissionPending={submissionPending}
                  onToolSelectionChange={toolCatalogState.setSelectedToolNames}
                  onToolProfileChange={toolCatalogState.applyToolProfile}
                  toolPreflight={toolPreflightState.estimate}
                  toolPreflightLoading={toolPreflightState.isLoading}
                  toolCatalogError={toolCatalogState.error}
                  toolPreflightError={toolPreflightState.error}
                  toolProfileFeedback={toolProfileFeedback}
                  toolProfileError={toolProfileError}
                  draftPrompt={draftPrompt}
                  onDraftChange={setDraftPrompt}
                  onSaveToolProfile={saveToolProfile}
                  onDuplicateToolProfile={duplicateToolProfile}
                  onRenameToolProfile={renameToolProfile}
                  onDeleteToolProfile={deleteToolProfile}
                  onRestoreToolProfile={restoreToolProfile}
                  onSetDefaultToolProfile={setDefaultToolProfile}
                  onStartApex={() => void handleStartApex()}
                  onStartWithBriefing={() => void handleStartWithBriefing()}
                  startDisabled={preflight.isChecking}
                  briefingMode={briefingMode}
                  onBriefingModeChange={handleBriefingModeChange}
                  briefingTargets={briefingTargets}
                  briefingControlsBusy={briefingControlsBusy}
                  briefingModeAvailable={briefingModeAvailable}
                  hasSnapshot={hasSnapshot}
                  isRefreshingAll={isRefreshingAll}
                  onRefreshAll={handleRefreshAll}
                  onGenerateBriefing={() => void handleGenerateBriefing()}
                  onRefreshAllAndGenerate={() => void handleRefreshAllAndGenerate()}
                  activeLocalModel={activeLocalModel}
                  loadingLocalAgent={loadingLocalAgent}
                  localLifecycleBusy={localLifecycleBusy}
                  onUnloadLocalModel={unloadLocalModel}
                />
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`hud-wing-column order-3 flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} xl:min-h-0 xl:flex xl:flex-col ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
            >
              <TelemetryCard
                title="Inbox"
                icon={Mail}
                ledState={emailLedState}
                onRefresh={() => handleRefreshConnector('email')}
                refreshDisabled={isRefreshingAll}
                statusMessage={emailStatusMessage}
                compactValue={inboxCompactValue}
                attentionTier={attentionTiers.inbox}
                attentionStaggerMs={attentionStagger.inbox}
                className={rightTelemetryPanelClass}
              >
                {emailRefreshing && !hasSnapshot ? (
                  <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                    Loading inbox…
                  </p>
                ) : (
                  <>
                    {emailInfo.count > 0 && (
                      <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
                        {emailInfo.count} Primary Messages
                      </p>
                    )}
                    {emailInfo.items.length > 0 ? (
                      <ul className="list-fade-mask min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                        {emailInfo.items.map((item, index) => (
                          <li
                            key={`${item.subject}-${item.time}-${index}`}
                            className="flex items-start justify-between gap-3"
                          >
                            <span className="flex min-w-0 items-start gap-2">
                              <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
                              <span className="break-words text-sm text-zinc-200">
                                {item.subject}
                              </span>
                            </span>
                            <span className="shrink-0 font-mono text-xs text-zinc-500">
                              {item.time}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : hasSnapshot ? (
                      <p className="text-sm text-[color:var(--hud-muted-text)]">
                        No unread emails.
                      </p>
                    ) : (
                      <p className="text-sm text-[color:var(--hud-muted-text)]">
                        Inbox unavailable.
                      </p>
                    )}
                  </>
                )}
              </TelemetryCard>

              <TelemetryCard
                title="News Wire"
                icon={Newspaper}
                ledState={newsLedState}
                onRefresh={() => handleRefreshConnector('news')}
                refreshDisabled={isRefreshingAll}
                statusMessage={newsStatusMessage}
                compactValue={newsCompactValue}
                attentionTier={attentionTiers.news}
                attentionStaggerMs={attentionStagger.news}
                className={rightTelemetryPanelClass}
              >
                {newsRefreshing && !hasSnapshot ? (
                  <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                    Loading news…
                  </p>
                ) : newsItems.length > 0 ? (
                  <ul className="list-fade-mask min-h-0 overflow-y-auto pr-1 scrollbar-thin">
                    {newsItems.map((item, index) => (
                      <li
                        key={`${item.topic}-${index}`}
                        className={
                          index < newsItems.length - 1
                            ? 'border-b border-zinc-800/60 py-3 first:pt-0'
                            : 'py-3 first:pt-0'
                        }
                      >
                        <p className="flex items-center gap-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--hud-accent)]">
                          <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
                          [{item.topic}]
                        </p>
                        <p className="mt-0.5 line-clamp-2 text-sm leading-relaxed text-zinc-200">
                          {item.headline}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : hasSnapshot ? (
                  <p className="text-sm text-[color:var(--hud-muted-text)]">
                    No news headlines available.
                  </p>
                ) : (
                  <p className="text-sm text-[color:var(--hud-muted-text)]">
                    News unavailable.
                  </p>
                )}
              </TelemetryCard>

              <TelemetryCard
                title="Reminders"
                icon={CheckSquare}
                ledState={resolveModuleLedState(
                  remindersModule,
                  remindersRefreshing,
                )}
                onRefresh={handleRefreshReminders}
                refreshDisabled={isRefreshingAll || isReminderRefreshPending}
                statusMessage={remindersStatusMessage}
                compactValue={remindersCompactValue}
                attentionTier={attentionTiers.reminders}
                attentionStaggerMs={attentionStagger.reminders}
                className={rightTelemetryPanelClass}
                role="region"
                aria-label="Active reminders"
                data-slot="reminders-card"
                headerAction={(
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setIsCompletedRemindersOpen(true)}
                      aria-label="Completed reminders"
                      title="Completed reminders"
                      className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[color:var(--hud-text)] transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                    >
                      <Clock className="size-3.5 text-[color:var(--hud-accent)]" strokeWidth={2} aria-hidden />
                    </button>
                    <ReminderQuickAdd onSave={handleReminderSave} />
                  </div>
                )}
              >
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  {activeReminders.length === 0 ? (
                    <div className="rounded-md border border-white/[0.06] bg-zinc-950/20 px-3 py-2">
                      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">
                        No pending reminders
                      </p>
                    </div>
                  ) : (
                    <ul className="list-fade-mask min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                      {activeReminders.map((reminder, index) => (
                        <ReminderListRow
                          key={reminder.id}
                          reminder={reminder}
                          index={index}
                          onMarkRead={handleMarkReminderRead}
                          onEdit={(id) => setReminderTaskDialog({ id, mode: 'edit' })}
                          onDelete={(id) => setReminderTaskDialog({ id, mode: 'delete' })}
                        />
                      ))}
                    </ul>
                  )}
                  {reminderSourceState && reminderSourceState !== 'live' ? (
                    <p className="mt-2 font-mono text-[9px] uppercase tracking-wide text-amber-200">
                      Reminder source: {reminderSourceState}
                    </p>
                  ) : null}
                  {reminderActionError ? (
                    <p className="mt-2 text-xs leading-relaxed text-red-200" role="alert">
                      {reminderActionError}
                    </p>
                  ) : null}
                  {activeReminders.some((item) => item.source === 'local') ? (
                    <button
                      type="button"
                      onClick={() => setIsReminderReviewOpen(true)}
                      className="mt-2 self-start font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white"
                    >
                      Review local reminders
                    </button>
                  ) : null}
                </div>
              </TelemetryCard>

            </div>
        </div>

          </>
        ) : (
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
            agentsStatus={agentsStatus}
            agentsStatusHydrated={agentsStatusHydrated}
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
