import {
  Calendar,
  CheckSquare,
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

import { ApexLogo } from './components/ApexLogo'
import { CelestialBackground } from './components/CelestialBackground'
import { CortexWorkspace } from './components/CortexWorkspace'
import { BriefingDigest } from './components/BriefingDigest'
import { CalendarEventList } from './components/CalendarEventList'
import { FootballFixtureList } from './components/FootballFixtureList'
import { MarketTickerCard } from './components/MarketTickerCard'
import { PreflightDialog } from './components/PreflightDialog'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderQuickAdd } from './components/ReminderQuickAdd'
import SettingsPanel from './components/SettingsPanel'
import { HomeCommandRail } from './components/HomeCommandRail'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VoiceSignalGlyph } from './components/VoiceSignalGlyph'
import { useApexData } from './hooks/useApexData'
import { useCortex } from './hooks/useCortex'
import { useAppActivation } from './hooks/useAppActivation'
import { useBriefingPipeline } from './hooks/useBriefingPipeline'
import { useLocalCommands } from './hooks/useLocalCommands'
import { useMarketData } from './hooks/useMarketData'
import { usePreflight } from './hooks/usePreflight'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import { useTelemetrySnapshot } from './hooks/useTelemetrySnapshot'
import { useVoiceDelivery } from './hooks/useVoiceDelivery'
import { API_ENDPOINTS } from './lib/api'
import { resolveAttentionStaggerMs, resolveTelemetryAttentionTier } from './lib/attentionTier'
import { resolveCalendarTelemetry } from './lib/calendarTelemetry'
import { resolveFootballTelemetry } from './lib/footballTelemetry'
import { moduleReasonLabel, resolveModuleLedState } from './lib/moduleTelemetry'
import { resolveWeatherFromModule } from './lib/weatherTelemetry'
import {
  filterAskApexSettingsForDevMode,
  parseSettingsResponse,
  resolveAppliedAgentSelection,
  resolveInitialAgentSelection,
} from './lib/settings'
import type {
  AgentKey,
  CloudEffort,
  LocalToolScope,
} from './types/telemetry'
import type { BriefingMode, SettingsResponse, VoiceMode } from './types/settings'

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
  'panthera',
  'mus',
  'sorex',
  'structured_digest',
]

function isBriefingMode(value: string): value is BriefingMode {
  return (VALID_BRIEFING_MODES as readonly string[]).includes(value)
}

const VALID_VOICE_MODES: readonly VoiceMode[] = ['off', 'manual', 'automatic']

function isVoiceMode(value: string): value is VoiceMode {
  return (VALID_VOICE_MODES as readonly string[]).includes(value)
}

function briefingModeInvolvesCloud(mode: BriefingMode): boolean {
  return mode === 'panthera'
}

function synthesisAgentForMode(mode: BriefingMode): string | null {
  if (mode === 'structured_digest') {
    return null
  }
  return mode
}

function isCloudAgentKey(
  agent: AgentKey,
  agentsStatus: { key: AgentKey; runtime: 'cloud' | 'local' }[],
): boolean {
  const match = agentsStatus.find((entry) => entry.key === agent)
  if (match) {
    return match.runtime === 'cloud'
  }
  return agent !== 'sorex' && agent !== 'mus'
}

export default function App(): ReactElement {
  const reminderPulseCount = 0
  const [activeAgent, setAgent] = useState<AgentKey>('panthera')
  const [cloudEffort, setCloudEffort] = useState<CloudEffort>('focused')
  const [briefingMode, setBriefingMode] = useState<BriefingMode>('panthera')
  const briefingModeSelectionTouchedRef = useRef(false)
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('automatic')
  const [workspace, setWorkspace] = useState<'home' | 'cortex'>('home')
  const [cloudAgent, setCloudAgent] = useState<Exclude<AgentKey, 'sorex' | 'mus' | 'acinonyx'>>('panthera')
  const [snapshotAttached, setSnapshotAttached] = useState(true)
  const [armedLocalToolScope, setArmedLocalToolScope] = useState<LocalToolScope | null>(null)
  const [cortexSessionId, setCortexSessionId] = useState(() =>
    globalThis.crypto?.randomUUID?.() ?? `cortex-${Date.now()}`,
  )
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const settingsButtonRef = useRef<HTMLButtonElement>(null)

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const apexData = useApexData()
  const {
    activeReminders,
    createReminder,
    demoModeActive,
    devModeActive,
    askApexEnabled,
    marketEnabled,
    defaultAgent,
    agentInitialSelection,
    briefingDefaultMode,
    voiceMode: bootVoiceMode,
    markReminderAsRead,
    applyBootSettings,
  } = apexData
  const { data: marketData, isLoading: isMarketLoading } = useMarketData(marketEnabled)

  const { activated, activate } = useAppActivation()
  const preflight = usePreflight()
  const telemetry = useTelemetrySnapshot()
  const briefing = useBriefingPipeline()
  const voiceDelivery = useVoiceDelivery()

  const {
    cortexHistory,
    isCortexQuerying,
    activeQueryAgent,
    cortexLatestTrace,
    cortexError,
    cortexContextUsage,
    agentsStatus,
    agentsStatusHydrated,
    queryAgent,
    isLocalModelActionPending,
    verifyingCloudAgent,
    loadLocalModel,
    unloadLocalModel,
    verifyCloudAgent,
    refreshAgentsStatus,
    clearCortexSession,
  } = useCortex(true, activeAgent)
  const isLocalAgent = activeAgent === 'sorex' || activeAgent === 'mus'
  const { commands: localCommands } = useLocalCommands(isLocalAgent)

  useEffect(() => {
    const armedScopeIsUnavailable = armedLocalToolScope && (
      !isLocalAgent ||
      !localCommands.some((command) => command.key === armedLocalToolScope && command.available)
    )
    if (!armedScopeIsUnavailable) return
    const timeoutId = window.setTimeout(() => setArmedLocalToolScope(null), 0)
    return () => window.clearTimeout(timeoutId)
  }, [armedLocalToolScope, isLocalAgent, localCommands])

  const agentSelectionHydratedRef = useRef(false)

  // Hydrate backend defaults once; later agent changes belong to the active session.
  useEffect(() => {
    const selection = resolveInitialAgentSelection(
      agentSelectionHydratedRef.current,
      agentInitialSelection,
      defaultAgent,
    )
    if (selection) {
      setAgent(selection.agent)
      if (selection.agent !== 'sorex' && selection.agent !== 'mus' && selection.agent !== 'acinonyx') {
        setCloudAgent(selection.agent)
      }
      if (selection.effort) {
        setCloudEffort(selection.effort)
      }
      agentSelectionHydratedRef.current = true
    }
  }, [agentInitialSelection, defaultAgent])

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
    (response: SettingsResponse, selectedAgent?: AgentKey) => {
      const selection = resolveAppliedAgentSelection(
        response,
        selectedAgent ?? activeAgent,
        agentSelectionHydratedRef.current || selectedAgent !== undefined,
      )
      applyBootSettings({
        askApexEnabled: response.settings.ask_apex.enabled,
        agentInitialSelection: selection,
        marketEnabled: response.settings.features.market,
      })
      setAgent(selection.agent)
      if (selection.agent !== 'sorex' && selection.agent !== 'mus' && selection.agent !== 'acinonyx') {
        setCloudAgent(selection.agent)
      }
      if (selection.effort) {
        setCloudEffort(selection.effort)
      }
      if (!briefingModeSelectionTouchedRef.current) {
        setBriefingMode(response.settings.briefing.default_mode)
      }
      setVoiceMode(response.settings.voice.mode)
    },
    [activeAgent, applyBootSettings],
  )

  // Cortex remembers both production runtime choices. This is deliberately
  // separate from DEV_MODE's Acinonyx startup override, which remains session-only.
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
        const askApex = settingsValues.ask_apex
        if (askApex && typeof askApex === 'object') {
          const values = askApex as Record<string, unknown>
          if (values.cloud_agent === 'panthera' || values.cloud_agent === 'neofelis' || values.cloud_agent === 'delphinus' || values.cloud_agent === 'orcinus') {
            setCloudAgent(values.cloud_agent)
          }
          if (values.effort === 'light' || values.effort === 'focused' || values.effort === 'extended') {
            setCloudEffort(values.effort)
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
    activeQueryAgent === 'sorex' ||
    activeQueryAgent === 'mus' ||
    liveSynthesis?.phase === 'loading' ||
    liveSynthesis?.phase === 'generating'

  const activeStep = pipelineState?.step ?? null
  const isBriefingRunning = briefing.status === 'loading'
  const isCompatibilitySegmentSurging =
    isBriefingRunning && activeStep !== null && activeStep >= 1 && activeStep <= 3

  const loadingLocalAgent = useMemo(
    () => agentsStatus.find((agent) => agent.loading) ?? null,
    [agentsStatus],
  )
  const activeLocalModel = useMemo(
    () =>
      agentsStatus.find(
        (agent) => agent.provider === 'ollama' && agent.active,
      ) ?? null,
    [agentsStatus],
  )
  const isLocalModelLoading =
    loadingLocalAgent !== null ||
    (liveSynthesis?.provider === 'ollama' && liveSynthesis.loading)
  const isLocalModelLoaded = activeLocalModel !== null
  const loadingDisplayName =
    loadingLocalAgent?.display_name ??
    (liveSynthesis?.agent ? `Apex ${liveSynthesis.agent}` : null)

  const glowColor = useMemo((): string => {
    if (briefing.status === 'error') {
      return '220, 38, 38' // Red
    }
    if (isLocalModelLoading) {
      return '249, 115, 22' // Rust orange (local model loading)
    }
    if (isCortexQuerying) {
      return '168, 85, 247' // Purple (Agent working)
    }
    if (activeStep === 4) {
      return '251, 191, 36' // Gold
    }
    if (briefing.status === 'success' && !isSpeaking) {
      return isLocalModelLoaded ? '249, 115, 22' : '15, 77, 184'
    }
    if (activeStep === 3) {
      return '168, 85, 247' // Purple/magenta (logo accent)
    }
    if (isBriefingRunning || activeStep === 1 || activeStep === 2) {
      return '57, 255, 136' // Green
    }
    if (isLocalModelLoaded) {
      return '249, 115, 22' // Rust orange (local model loaded)
    }
    if (activated) {
      return '15, 77, 184' // Calm blue — activated home, no briefing/error state
    }
    return '15, 23, 42' // Deep Slate Blue
  }, [
    briefing.status,
    activeStep,
    isSpeaking,
    isLocalModelLoading,
    isCortexQuerying,
    isLocalModelLoaded,
    isBriefingRunning,
    activated,
  ])

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
  const centerColumnActiveClasses = 'grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] pt-0 xl:max-w-[33.33%] xl:flex-1 xl:min-h-0'

  // The logo is always visible and the insights panel stays mounted while the
  // Home telemetry columns transition around it.
  const showDigest = !isDormant
  const digestWrapperClass = [
    'hud-digest-wrapper transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu min-h-0 w-full',
    showDigest
      ? 'max-h-[220px] xl:max-h-[240px] opacity-100 mb-3 xl:mb-4 overflow-visible'
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
      synthesis_agent: synthesisAgentForMode(briefingMode),
      involves_cloud: briefingModeInvolvesCloud(briefingMode),
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

  const isRefreshingAll = telemetry.isRefreshingAll
  const isTelemetryCollecting = isRefreshingAll || telemetry.refreshingConnectors.size > 0
  const hasSnapshot = telemetry.snapshot !== null
  const briefingControlsBusy =
    preflight.isChecking || preflight.dialogOpen || isBriefingRunning || isTelemetryCollecting
  const selectedBriefingAgent = synthesisAgentForMode(briefingMode)
  const briefingModeAvailable =
    selectedBriefingAgent === null ||
    (agentsStatusHydrated &&
      agentsStatus.some(
        (agent) =>
          agent.key === selectedBriefingAgent &&
          ['available', 'configured', 'verified'].includes(agent.status),
      ))
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
  const remindersRefreshing = isConnectorRefreshing('reminders')

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
    : { temperatureF: null, detail: '', condition: null }
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

  const handleMarkReminderRead = (id: number): void => {
    void markReminderAsRead(id)
  }

  const handleGenerateBriefing = useCallback(async (): Promise<void> => {
    const snapshotId = telemetry.snapshot?.snapshot_id
    if (!snapshotId) {
      return
    }
    const resolution = await preflight.requestOperation('generate_briefing', {
      briefing_mode: briefingMode,
      synthesis_agent: synthesisAgentForMode(briefingMode),
      involves_cloud: briefingModeInvolvesCloud(briefingMode),
    })
    if (resolution !== 'proceed') {
      return
    }
    await briefing.generateFromSnapshot(snapshotId, briefingMode)
  }, [preflight, briefingMode, briefing, telemetry.snapshot?.snapshot_id])

  const handleRefreshAllAndGenerate = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('generate_briefing', {
      briefing_mode: briefingMode,
      synthesis_agent: synthesisAgentForMode(briefingMode),
      involves_cloud: briefingModeInvolvesCloud(briefingMode),
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
  const queryAgentWithContext = useCallback(
    async (
      prompt: string,
      agent: AgentKey,
      toolScope?: LocalToolScope | null,
    ): Promise<void> => {
      const resolution = await preflight.requestOperation('cortex_query', {
        synthesis_agent: agent,
        involves_cloud: isCloudAgentKey(agent, agentsStatus),
      })
      if (resolution !== 'proceed') {
        return
      }
      await queryAgent(prompt, agent, {
        snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
        toolScope,
        effort: isCloudAgentKey(agent, agentsStatus) ? cloudEffort : null,
        sessionId: cortexSessionId,
      })
    },
    [
      preflight,
      queryAgent,
      telemetry.snapshot?.snapshot_id,
      agentsStatus,
      cloudEffort,
      snapshotAttached,
      cortexSessionId,
    ],
  )

  const persistAskApexSettings = useCallback(
    async (askApex: Record<string, unknown>, selectedAgent?: AgentKey): Promise<void> => {
      const payload = devModeActive ? filterAskApexSettingsForDevMode(askApex) : askApex
      if (Object.keys(payload).length === 0) {
        return
      }
      try {
        const response = await fetch(API_ENDPOINTS.settings, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ask_apex: payload }),
        })
        if (!response.ok) {
          return
        }
        const body: unknown = await response.json()
        const parsed = parseSettingsResponse(body)
        if (parsed) {
          handleSettingsApplied(parsed, selectedAgent)
          await refreshAgentsStatus()
        }
      } catch {
        // The session selection remains usable if local preference persistence fails.
      }
    },
    [devModeActive, handleSettingsApplied, refreshAgentsStatus],
  )

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

  const handleBriefingModeChange = useCallback((mode: BriefingMode): void => {
    briefingModeSelectionTouchedRef.current = true
    setBriefingMode(mode)
    void persistBriefingMode(mode)
  }, [persistBriefingMode])

  const handleAgentChange = useCallback((agent: AgentKey): void => {
    setAgent(agent)
    if (agent !== 'sorex' && agent !== 'mus') {
      setArmedLocalToolScope(null)
    }
    if (agent === 'acinonyx') {
      void persistAskApexSettings({ runtime: 'cloud', effort: cloudEffort }, agent)
      return
    }
    if (agent === 'sorex' || agent === 'mus') {
      void persistAskApexSettings({ runtime: 'local', local_agent: agent }, agent)
      return
    }
    setCloudAgent(agent)
    void persistAskApexSettings({ runtime: 'cloud', cloud_agent: agent, effort: cloudEffort }, agent)
  }, [cloudEffort, persistAskApexSettings])

  const handleEffortChange = useCallback((effort: CloudEffort): void => {
    setCloudEffort(effort)
    void persistAskApexSettings({ runtime: 'cloud', cloud_agent: cloudAgent, effort: effort }, activeAgent)
  }, [activeAgent, cloudAgent, persistAskApexSettings])

  const handleGoogleSearchChange = useCallback((enabled: boolean): void => {
    void persistAskApexSettings({ neofelis_google_search_enabled: enabled }, activeAgent)
  }, [activeAgent, persistAskApexSettings])

  const handleGoogleMapsChange = useCallback((enabled: boolean): void => {
    void persistAskApexSettings({ neofelis_google_maps_enabled: enabled }, activeAgent)
  }, [activeAgent, persistAskApexSettings])

  const handleDelphinusXSearchChange = useCallback((enabled: boolean): void => {
    void persistAskApexSettings({ delphinus_x_search_enabled: enabled }, activeAgent)
  }, [activeAgent, persistAskApexSettings])

  const handleOrcinusXSearchChange = useCallback((enabled: boolean): void => {
    void persistAskApexSettings({ orcinus_x_search_enabled: enabled }, activeAgent)
  }, [activeAgent, persistAskApexSettings])

  const handleNewCortexSession = useCallback((): void => {
    clearCortexSession(activeAgent)
    setSnapshotAttached(false)
    setArmedLocalToolScope(null)
    setCortexSessionId(globalThis.crypto?.randomUUID?.() ?? `cortex-${Date.now()}`)
  }, [activeAgent, clearCortexSession])

  const handleHomeSubmit = useCallback((query: string, agent: AgentKey, toolScope?: LocalToolScope | null): void => {
    setWorkspace('cortex')
    void queryAgentWithContext(query, agent, toolScope)
  }, [queryAgentWithContext])

  return (
    <main
      className="hud-app-shell hud-layout-fullscreen relative isolate flex h-dvh w-full min-h-0 flex-col overflow-x-hidden bg-[var(--hud-bg)] p-4 md:p-6"
      style={{ '--glow-color': glowColor } as CSSProperties}
    >
      <CelestialBackground />

      <div
        className="absolute inset-0 z-[var(--z-reactive-glow)] pointer-events-none overflow-hidden"
        style={{ '--glow-color': glowColor } as CSSProperties}
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
          onApplied={handleSettingsApplied}
        />

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
                  weatherCondition={weatherInfo.condition}
                  ledState={weatherLedState}
                  onRefresh={() => handleRefreshConnector('weather')}
                  refreshDisabled={isRefreshingAll}
                  statusMessage={weatherStatusMessage}
                  compactValue={weatherBody}
                  attentionTier={attentionTiers.weather}
                  attentionStaggerMs={attentionStagger.weather}
                  className={`min-h-0 ${weatherPanelLayoutClass}`}
                >
                  <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                    {weatherBody}
                  </p>
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
                style={{ background: 'rgba(var(--glow-color), 0.15)' }}
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
                  synthesisLabel={
                    briefing.synthesisProvider
                      ? [briefing.synthesisProvider, briefing.synthesisAgent]
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
                    className={`filter drop-shadow-[0_0_24px_rgba(var(--glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--glow-color),0.6)] ${isDormant ? 'scale-115 xl:scale-125' : 'scale-100'}`}
                  >
                    <ApexLogo
                      step={activeStep}
                      status={logoStatus}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      isCortexQuerying={isCortexQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      isLocalModelLoaded={isLocalModelLoaded}
                      isTelemetryCollecting={isTelemetryCollecting}
                      isOuterSegmentSurging={isCompatibilitySegmentSurging}
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
                    />
                  </div>
                </div>
              </div>
              <div className="flex w-full flex-col items-center">
                <HomeCommandRail
                  activated={activated}
                  askApexEnabled={Boolean(askApexEnabled)}
                  activeAgent={activeAgent}
                  agentsStatus={agentsStatus}
                  agentsStatusHydrated={agentsStatusHydrated}
                  isCortexQuerying={isCortexQuerying}
                  verifyingCloudAgent={verifyingCloudAgent}
                  onAgentChange={handleAgentChange}
                  onVerifyCloudAgent={verifyCloudAgent}
                  onAgentSubmit={handleHomeSubmit}
                  onStartApex={() => void handleStartApex()}
                  onStartWithBriefing={() => void handleStartWithBriefing()}
                  startDisabled={preflight.isChecking}
                  briefingMode={briefingMode}
                  onBriefingModeChange={handleBriefingModeChange}
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
                onRefresh={() => handleRefreshConnector('reminders')}
                refreshDisabled={isRefreshingAll}
                statusMessage={remindersStatusMessage}
                compactValue={remindersCompactValue}
                attentionTier={attentionTiers.reminders}
                attentionStaggerMs={attentionStagger.reminders}
                className={rightTelemetryPanelClass}
                role="region"
                aria-label="Active reminders"
                data-slot="reminders-card"
                headerAction={<ReminderQuickAdd onSave={createReminder} />}
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
                        />
                      ))}
                    </ul>
                  )}
                </div>
              </TelemetryCard>

            </div>
        </div>

          </>
        ) : (
          <CortexWorkspace
            activeAgent={activeAgent}
            cloudEffort={cloudEffort}
            askApexEnabled={Boolean(askApexEnabled)}
            agentsStatus={agentsStatus}
            agentsStatusHydrated={agentsStatusHydrated}
            history={cortexHistory}
            latestTrace={cortexLatestTrace}
            error={cortexError}
            contextUsage={cortexContextUsage}
            commands={localCommands}
            armedToolScope={armedLocalToolScope}
            onArmedToolScopeChange={setArmedLocalToolScope}
            isQuerying={isCortexQuerying}
            lifecycleBusy={localLifecycleBusy}
            lifecycleActionPending={isLocalModelActionPending}
            verifyingCloudAgent={verifyingCloudAgent}
            onLoadLocalModel={loadLocalModel}
            onUnloadLocalModel={unloadLocalModel}
            onVerifyCloudAgent={verifyCloudAgent}
            snapshotAttached={snapshotAttached}
            snapshotAvailable={telemetry.snapshot !== null}
            onSnapshotAttachedChange={setSnapshotAttached}
            onAgentChange={handleAgentChange}
            onEffortChange={handleEffortChange}
            onGoogleSearchChange={handleGoogleSearchChange}
            onGoogleMapsChange={handleGoogleMapsChange}
            onDelphinusXSearchChange={handleDelphinusXSearchChange}
            onOrcinusXSearchChange={handleOrcinusXSearchChange}
            onSubmit={handleHomeSubmit}
            onNewSession={handleNewCortexSession}
          />
        )}
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
