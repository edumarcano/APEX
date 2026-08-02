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
import { LocalModelControl } from './components/LocalModelControl'
import { CelestialBackground } from './components/CelestialBackground'
import { CortexWorkspace } from './components/CortexWorkspace'
import { AskApexBar } from './components/AskApexBar'
import { BriefingDigest } from './components/BriefingDigest'
import { BriefingGenerateControl } from './components/BriefingControls'
import { CalendarEventList } from './components/CalendarEventList'
import { FootballFixtureList } from './components/FootballFixtureList'
import { MarketTickerCard } from './components/MarketTickerCard'
import { PreflightDialog } from './components/PreflightDialog'
import { ReminderListRow } from './components/ReminderListRow'
import SettingsPanel from './components/SettingsPanel'
import { StandbyActions } from './components/StandbyActions'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VoiceSignalGlyph } from './components/VoiceSignalGlyph'
import { useApexData } from './hooks/useApexData'
import { useApexAssistant } from './hooks/useApexAssistant'
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
  parseSettingsResponse,
  resolveAssistantProfile,
  resolveInitialAssistantSelection,
} from './lib/settings'
import type {
  AssistantProfile,
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

function synthesisProfileForMode(mode: BriefingMode): string | null {
  if (mode === 'structured_digest') {
    return null
  }
  return mode
}

function isCloudAssistantProfile(
  profile: AssistantProfile,
  profilesStatus: { key: AssistantProfile; mode: 'cloud' | 'local' }[],
): boolean {
  const match = profilesStatus.find((entry) => entry.key === profile)
  if (match) {
    return match.mode === 'cloud'
  }
  return profile !== 'sorex' && profile !== 'mus'
}

export default function App(): ReactElement {
  const [reminderPulseCount] = useState(0)
  const [agentProfile, setAgentProfile] = useState<AssistantProfile>('panthera')
  const [cloudEffort, setCloudEffort] = useState<CloudEffort>('focused')
  const [briefingMode, setBriefingMode] = useState<BriefingMode>('panthera')
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('automatic')
  const [workspace, setWorkspace] = useState<'overview' | 'cortex'>('overview')
  const [cloudProfile, setCloudProfile] = useState<Exclude<AssistantProfile, 'sorex' | 'mus' | 'acinonyx'>>('panthera')
  const [snapshotAttached, setSnapshotAttached] = useState(true)
  const [neofelisGoogleSearchEnabled, setNeofelisGoogleSearchEnabled] = useState(true)
  const [neofelisGoogleMapsEnabled, setNeofelisGoogleMapsEnabled] = useState(true)
  const [delphinusXSearchEnabled, setDelphinusXSearchEnabled] = useState(true)
  const [orcinusXSearchEnabled, setOrcinusXSearchEnabled] = useState(true)
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
    demoModeActive,
    devModeActive,
    askApexEnabled,
    marketEnabled,
    defaultProfile,
    assistantInitialSelection,
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

  const showAskApexBar = activated && Boolean(askApexEnabled)

  const {
    assistantHistory,
    isAssistantQuerying,
    activeQueryProfile,
    assistantLatestTrace,
    assistantError,
    assistantContextUsage,
    profilesStatus,
    profilesStatusHydrated,
    queryAssistant,
    isLocalModelActionPending,
    verifyingCloudProfile,
    loadLocalModel,
    unloadLocalModel,
    verifyCloudProfile,
    clearAssistantChat,
  } = useApexAssistant(true, agentProfile)
  const isLocalAgentProfile = agentProfile === 'sorex' || agentProfile === 'mus'
  const { commands: localCommands } = useLocalCommands(isLocalAgentProfile)

  useEffect(() => {
    const armedScopeIsUnavailable = armedLocalToolScope && (
      !isLocalAgentProfile ||
      !localCommands.some((command) => command.key === armedLocalToolScope && command.available)
    )
    if (!armedScopeIsUnavailable) return
    const timeoutId = window.setTimeout(() => setArmedLocalToolScope(null), 0)
    return () => window.clearTimeout(timeoutId)
  }, [armedLocalToolScope, isLocalAgentProfile, localCommands])

  const assistantSelectionHydratedRef = useRef(false)

  // Hydrate backend defaults once; later profile changes belong to the active session.
  useEffect(() => {
    const selection = resolveInitialAssistantSelection(
      assistantSelectionHydratedRef.current,
      assistantInitialSelection,
      defaultProfile,
    )
    if (selection) {
      setAgentProfile(selection.profile)
      if (selection.profile !== 'sorex' && selection.profile !== 'mus' && selection.profile !== 'acinonyx') {
        setCloudProfile(selection.profile)
      }
      if (selection.effort) {
        setCloudEffort(selection.effort)
      }
      assistantSelectionHydratedRef.current = true
    }
  }, [assistantInitialSelection, defaultProfile])

  useEffect(() => {
    if (briefingDefaultMode && isBriefingMode(briefingDefaultMode)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Mirrors asynchronous boot configuration into local controls.
      setBriefingMode(briefingDefaultMode)
    }
    if (bootVoiceMode && isVoiceMode(bootVoiceMode)) {
      setVoiceMode(bootVoiceMode)
    }
  }, [bootVoiceMode, briefingDefaultMode])

  const handleSettingsApplied = useCallback(
    (response: SettingsResponse) => {
      // DEV_MODE keeps Acinonyx as the effective profile without
      // writing it into saved production preferences.
      const selection = response.dev_mode_active
        ? {
            mode: 'cloud' as const,
            profile: 'acinonyx' as AssistantProfile,
            effort: response.settings.assistant.cloud_effort,
          }
        : {
            mode: response.settings.assistant.mode,
            profile: resolveAssistantProfile(response.settings.assistant),
            effort:
              response.settings.assistant.mode === 'cloud'
                ? response.settings.assistant.cloud_effort
                : null,
          }
      applyBootSettings({
        askApexEnabled: response.settings.assistant.enabled,
        assistantInitialSelection: selection,
        marketEnabled: response.settings.features.market,
      })
      setAgentProfile(selection.profile)
      if (selection.profile !== 'sorex' && selection.profile !== 'mus' && selection.profile !== 'acinonyx') {
        setCloudProfile(selection.profile)
      }
      if (selection.effort) {
        setCloudEffort(selection.effort)
      }
      setNeofelisGoogleSearchEnabled(
        response.settings.assistant.neofelis_google_search_enabled,
      )
      setNeofelisGoogleMapsEnabled(response.settings.assistant.neofelis_google_maps_enabled)
      setDelphinusXSearchEnabled(response.settings.assistant.delphinus_x_search_enabled)
      setOrcinusXSearchEnabled(response.settings.assistant.orcinus_x_search_enabled)
      setBriefingMode(response.settings.briefing.default_mode)
      setVoiceMode(response.settings.voice.mode)
    },
    [applyBootSettings],
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
        const assistant = (body as { settings?: { assistant?: unknown } }).settings?.assistant
        if (!assistant || typeof assistant !== 'object') return
        const values = assistant as Record<string, unknown>
        if (values.cloud_profile === 'panthera' || values.cloud_profile === 'neofelis' || values.cloud_profile === 'delphinus' || values.cloud_profile === 'orcinus') {
          setCloudProfile(values.cloud_profile)
        }
        if (values.cloud_effort === 'light' || values.cloud_effort === 'focused' || values.cloud_effort === 'extended') {
          setCloudEffort(values.cloud_effort)
        }
        if (typeof values.neofelis_google_search_enabled === 'boolean') {
          setNeofelisGoogleSearchEnabled(values.neofelis_google_search_enabled)
        }
        if (typeof values.neofelis_google_maps_enabled === 'boolean') {
          setNeofelisGoogleMapsEnabled(values.neofelis_google_maps_enabled)
        }
        if (typeof values.delphinus_x_search_enabled === 'boolean') {
          setDelphinusXSearchEnabled(values.delphinus_x_search_enabled)
        }
        if (typeof values.orcinus_x_search_enabled === 'boolean') {
          setOrcinusXSearchEnabled(values.orcinus_x_search_enabled)
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
    activeQueryProfile === 'sorex' ||
    activeQueryProfile === 'mus' ||
    liveSynthesis?.phase === 'loading' ||
    liveSynthesis?.phase === 'generating'

  const activeStep = pipelineState?.step ?? null
  const isBriefingRunning = briefing.status === 'loading'
  const isCompatibilitySegmentSurging =
    isBriefingRunning && activeStep !== null && activeStep >= 1 && activeStep <= 3

  const loadingLocalProfile = useMemo(
    () => profilesStatus.find((profile) => profile.loading) ?? null,
    [profilesStatus],
  )
  const activeLocalModel = useMemo(
    () =>
      profilesStatus.find(
        (profile) => profile.provider === 'ollama' && profile.active,
      ) ?? null,
    [profilesStatus],
  )
  const isLocalModelLoading =
    loadingLocalProfile !== null ||
    (liveSynthesis?.provider === 'ollama' && liveSynthesis.loading)
  const isLocalModelLoaded = activeLocalModel !== null
  const loadingDisplayName =
    loadingLocalProfile?.display_name ??
    (liveSynthesis?.profile ? `Apex ${liveSynthesis.profile}` : null)

  const glowColor = useMemo((): string => {
    if (briefing.status === 'error') {
      return '220, 38, 38' // Red
    }
    if (isLocalModelLoading) {
      return '249, 115, 22' // Rust orange (local model loading)
    }
    if (isAssistantQuerying) {
      return '168, 85, 247' // Purple (assistant working)
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
      return '15, 77, 184' // Calm blue — activated overview, no briefing/error state
    }
    return '15, 23, 42' // Deep Slate Blue
  }, [
    briefing.status,
    activeStep,
    isSpeaking,
    isLocalModelLoading,
    isAssistantQuerying,
    isLocalModelLoaded,
    isBriefingRunning,
    activated,
  ])

  const pendingReminderCount = activeReminders.length
  const isDormant = !activated
  // Overview retains its full desktop HUD. Cortex owns assistant visibility
  // and never changes polling, request, speech, or briefing lifecycles.
  const useFullscreenOverviewLayout = true
  const isConsoleCompact = false

  const wingTransition =
    'transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)]'
  const wingHeightClass = useFullscreenOverviewLayout ? 'xl:h-full' : 'h-auto'
  const leftWingDormantClasses = useFullscreenOverviewLayout
    ? 'opacity-0 -translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
    : 'hidden'
  const leftWingActiveClasses = useFullscreenOverviewLayout
    ? 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
    : 'opacity-100 translate-x-0 scale-100 pointer-events-auto max-w-full flex-none overflow-visible'
  const rightWingDormantClasses = useFullscreenOverviewLayout
    ? 'opacity-0 translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
    : 'hidden'
  const rightWingActiveClasses = useFullscreenOverviewLayout
    ? 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
    : 'opacity-100 translate-x-0 scale-100 pointer-events-auto max-w-full flex-none overflow-visible'
  const centerColumnDormantClasses = useFullscreenOverviewLayout
    ? 'h-full min-h-0 flex flex-col justify-center xl:max-w-full xl:flex-1'
    : 'h-auto min-h-0 flex flex-col justify-center'
  const centerColumnActiveClasses = useFullscreenOverviewLayout
    ? 'h-full min-h-0 flex flex-col justify-start pt-0 xl:max-w-[33.33%] xl:flex-1 xl:min-h-0'
    : 'h-auto min-h-0 flex flex-col justify-start pt-0'

  // The logo is always visible and the insights panel stays mounted while the
  // desktop console opens in the right column.
  const showDigest = !isDormant
  const digestWrapperClass = [
    'hud-digest-wrapper transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu min-h-0 w-full',
    showDigest
      ? 'max-h-[220px] xl:max-h-[240px] opacity-100 mb-3 xl:mb-4 overflow-visible'
      : 'max-h-0 opacity-0 mb-0 overflow-hidden pointer-events-none',
  ].join(' ')

  const logoShellClass = 'hud-logo-shell shrink-0 py-4 xl:py-0'

  const largeLogoWrapperClass = [
    'hud-logo-wrapper transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu flex flex-col items-center opacity-100 scale-100',
    isDormant
      ? 'h-64 justify-center xl:h-auto xl:flex-1'
      : 'h-72 justify-center xl:h-80',
  ].join(' ')

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
      synthesis_profile: synthesisProfileForMode(briefingMode),
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
  const selectedBriefingProfile = synthesisProfileForMode(briefingMode)
  const briefingModeAvailable =
    selectedBriefingProfile === null ||
    (profilesStatusHydrated &&
      profilesStatus.some(
        (profile) =>
          profile.key === selectedBriefingProfile &&
          ['available', 'configured', 'verified'].includes(profile.status),
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

  const wingGapClass = isConsoleCompact ? 'gap-3' : 'gap-4'
  const weatherPanelLayoutClass = useFullscreenOverviewLayout
    ? 'xl:flex-[0.5_1_0] xl:min-h-0'
    : 'hud-panel-natural min-h-[8rem]'
  const eventsPanelLayoutClass = useFullscreenOverviewLayout
    ? 'xl:flex-[1.5_1_0] xl:min-h-0'
    : 'hud-panel-natural min-h-[11rem]'
  const marketPanelLayoutClass = useFullscreenOverviewLayout
    ? 'xl:flex-[1_1_0]'
    : 'hud-panel-natural min-h-[12rem]'
  const rightTelemetryPanelClass = isConsoleCompact
    ? 'xl:hidden'
    : useFullscreenOverviewLayout
      ? 'flex-none xl:flex-1 xl:min-h-0'
      : 'hud-panel-natural min-h-[10rem]'

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
      synthesis_profile: synthesisProfileForMode(briefingMode),
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
      synthesis_profile: synthesisProfileForMode(briefingMode),
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

  const weatherCompactValue = primaryTemperatureF != null ? `${primaryTemperatureF}°` : null
  const weatherConditionCompactValue =
    primaryTemperatureF != null && weatherBody.trim().length > 0
      ? `${primaryTemperatureF}°, ${weatherBody}`
      : weatherCompactValue
  const eventsCompactValue = hasSnapshot
    ? [
        calendarInfo.totalCount > 0 ? `${calendarInfo.totalCount} calendar` : null,
        footballInfo.fixtures.length > 0 ? `${footballInfo.fixtures.length} football` : null,
      ].filter((value): value is string => value !== null).join(' · ') || 'No events'
    : null
  const inboxCompactValue = hasSnapshot ? `${emailInfo.count} unread` : null
  const newsCompactValue = hasSnapshot ? `${newsItems.length} headlines` : null
  const remindersCompactValue = `${pendingReminderCount} pending`
  const queryAssistantWithContext = useCallback(
    async (
      prompt: string,
      profile: AssistantProfile,
      toolScope?: LocalToolScope | null,
    ): Promise<void> => {
      const resolution = await preflight.requestOperation('assistant_query', {
        synthesis_profile: profile,
        involves_cloud: isCloudAssistantProfile(profile, profilesStatus),
      })
      if (resolution !== 'proceed') {
        return
      }
      await queryAssistant(prompt, profile, {
        snapshotId: snapshotAttached ? telemetry.snapshot?.snapshot_id ?? null : null,
        toolScope,
        effort: isCloudAssistantProfile(profile, profilesStatus)
          ? profile === 'acinonyx' ? 'focused' : cloudEffort
          : null,
        sessionId: cortexSessionId,
      })
    },
    [
      preflight,
      queryAssistant,
      telemetry.snapshot?.snapshot_id,
      profilesStatus,
      cloudEffort,
      snapshotAttached,
      cortexSessionId,
    ],
  )

  const persistAssistantSettings = useCallback(
    async (assistant: Record<string, unknown>): Promise<void> => {
      if (devModeActive) {
        return
      }
      try {
        const response = await fetch(API_ENDPOINTS.settings, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assistant }),
        })
        if (!response.ok) {
          return
        }
        const body: unknown = await response.json()
        const parsed = parseSettingsResponse(body)
        if (parsed) {
          handleSettingsApplied(parsed)
        }
      } catch {
        // The session selection remains usable if local preference persistence fails.
      }
    },
    [devModeActive, handleSettingsApplied],
  )

  const handleProfileChange = useCallback((profile: AssistantProfile): void => {
    setAgentProfile(profile)
    if (profile !== 'sorex' && profile !== 'mus') {
      setArmedLocalToolScope(null)
    }
    if (profile === 'acinonyx') {
      void persistAssistantSettings({ mode: 'cloud', cloud_effort: cloudEffort })
      return
    }
    if (profile === 'sorex' || profile === 'mus') {
      void persistAssistantSettings({ mode: 'local', local_profile: profile })
      return
    }
    setCloudProfile(profile)
    void persistAssistantSettings({ mode: 'cloud', cloud_profile: profile, cloud_effort: cloudEffort })
  }, [cloudEffort, persistAssistantSettings])

  const handleEffortChange = useCallback((effort: CloudEffort): void => {
    setCloudEffort(effort)
    void persistAssistantSettings({ mode: 'cloud', cloud_profile: cloudProfile, cloud_effort: effort })
  }, [cloudProfile, persistAssistantSettings])

  const handleGoogleSearchChange = useCallback((enabled: boolean): void => {
    setNeofelisGoogleSearchEnabled(enabled)
    void persistAssistantSettings({ neofelis_google_search_enabled: enabled })
  }, [persistAssistantSettings])

  const handleGoogleMapsChange = useCallback((enabled: boolean): void => {
    setNeofelisGoogleMapsEnabled(enabled)
    void persistAssistantSettings({ neofelis_google_maps_enabled: enabled })
  }, [persistAssistantSettings])

  const handleDelphinusXSearchChange = useCallback((enabled: boolean): void => {
    setDelphinusXSearchEnabled(enabled)
    void persistAssistantSettings({ delphinus_x_search_enabled: enabled })
  }, [persistAssistantSettings])

  const handleOrcinusXSearchChange = useCallback((enabled: boolean): void => {
    setOrcinusXSearchEnabled(enabled)
    void persistAssistantSettings({ orcinus_x_search_enabled: enabled })
  }, [persistAssistantSettings])

  const handleNewCortexSession = useCallback((): void => {
    clearAssistantChat(agentProfile)
    setSnapshotAttached(false)
    setArmedLocalToolScope(null)
    setCortexSessionId(globalThis.crypto?.randomUUID?.() ?? `cortex-${Date.now()}`)
  }, [agentProfile, clearAssistantChat])

  const handleOverviewSubmit = useCallback((query: string, profile: AssistantProfile, toolScope?: LocalToolScope | null): void => {
    setWorkspace('cortex')
    void queryAssistantWithContext(query, profile, toolScope)
  }, [queryAssistantWithContext])

  return (
    <main
      className={`hud-app-shell ${useFullscreenOverviewLayout ? 'hud-layout-fullscreen' : 'hud-layout-compact'} relative isolate flex h-dvh w-full min-h-0 flex-col overflow-x-hidden bg-[var(--hud-bg)] p-4 md:p-6`}
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
            status={briefing.status === 'idle' && activated ? (hasSnapshot ? 'success' : isRefreshingAll ? 'loading' : 'idle') : briefing.status}
            confidenceScore={telemetry.snapshot?.sync_health_score ?? briefing.confidenceScore}
            failedConnectors={telemetry.snapshot?.failed_connectors ?? briefing.failedConnectors}
            connectorHealth={telemetry.snapshot?.connector_health ?? briefing.connectorHealth}
            demoModeActive={demoModeActive}
            devModeActive={devModeActive}
            briefingMode={briefingMode}
            onBriefingModeChange={setBriefingMode}
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            briefingControlsBusy={briefingControlsBusy}
            onOpenSettings={() => setIsSettingsOpen(true)}
            settingsButtonRef={settingsButtonRef}
            workspaceNavigation={<nav className="flex items-center justify-center gap-1" aria-label="Workspace">
            <button type="button" onClick={() => setWorkspace('overview')} aria-pressed={workspace === 'overview'} className={`rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] ${workspace === 'overview' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'text-zinc-500 hover:text-zinc-200'}`}>Overview</button>
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
          isAssistantQuerying={isAssistantQuerying}
          profilesStatus={profilesStatus}
          profilesStatusHydrated={profilesStatusHydrated}
          failedConnectors={briefing.failedConnectors}
          hasBriefingEvidence={briefing.status === 'success' || briefing.status === 'error'}
          onApplied={handleSettingsApplied}
        />

        {workspace === 'overview' ? (
          <>
        <div className={`hud-body-layout flex w-full flex-col gap-4 overflow-visible ${useFullscreenOverviewLayout ? 'xl:h-full xl:min-h-0 xl:flex-1 xl:flex-row xl:overflow-hidden xl:gap-6' : 'flex-none'}`}>
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`hud-wing-column ${useFullscreenOverviewLayout ? 'order-2 xl:order-1' : 'order-2'} flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useFullscreenOverviewLayout ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <div className={`flex min-h-0 flex-col ${wingGapClass} xl:flex ${useFullscreenOverviewLayout ? 'xl:flex-1' : ''}`}>
                {isConsoleCompact ? (
                  <>
                    <TelemetryCard
                      title="Weather"
                      icon={CloudSun}
                      primaryTemperatureF={primaryTemperatureF}
                      weatherCondition={weatherInfo.condition}
                      ledState={weatherLedState}
                      onRefresh={() => handleRefreshConnector('weather')}
                      refreshDisabled={isRefreshingAll}
                      statusMessage={weatherStatusMessage}
                      isCompact
                      compactValue={weatherConditionCompactValue}
                      attentionTier={attentionTiers.weather}
                      attentionStaggerMs={attentionStagger.weather}
                      className="hidden xl:flex xl:min-h-[3.75rem] xl:flex-[0.58_1_0]"
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
                      className="hidden min-h-0 xl:flex xl:flex-[2.05_1_0]"
                    >
                      {calendarRefreshing && !hasSnapshot ? (
                        <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                          Loading schedule…
                        </p>
                      ) : (
                        <>
                          <CalendarEventList
                            compact
                            telemetry={calendarInfo}
                            hasSnapshot={hasSnapshot}
                          />
                          <FootballFixtureList telemetry={footballInfo} module={footballModule} hasSnapshot={hasSnapshot} />
                        </>
                      )}
                    </TelemetryCard>

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
                      className="hidden min-h-0 xl:flex xl:flex-[1.2_1_0]"
                    >
                      {emailRefreshing && !hasSnapshot ? (
                        <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                          Loading inbox...
                        </p>
                      ) : emailInfo.items.length > 0 ? (
                        <ul className="list-fade-mask min-h-0 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                          {emailInfo.items.slice(0, 3).map((item, index) => (
                            <li
                              key={`${item.subject}-${item.time}-${index}`}
                              className="flex items-start justify-between gap-3"
                            >
                              <span className="flex min-w-0 items-start gap-2">
                                <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
                                <span className="truncate text-sm text-zinc-200">
                                  {item.subject}
                                </span>
                              </span>
                              <span className="shrink-0 font-mono text-xs text-zinc-500">
                                {item.time}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-[color:var(--hud-muted-text)]">
                          {hasSnapshot ? 'No unread emails.' : 'Inbox unavailable.'}
                        </p>
                      )}
                    </TelemetryCard>

                    <TelemetryCard
                      title="News Wire"
                      icon={Newspaper}
                      ledState={newsLedState}
                      onRefresh={() => handleRefreshConnector('news')}
                      refreshDisabled={isRefreshingAll}
                      statusMessage={newsStatusMessage}
                      isCompact
                      compactValue={newsCompactValue}
                      attentionTier={attentionTiers.news}
                      attentionStaggerMs={attentionStagger.news}
                      className="hidden xl:flex xl:min-h-[3.75rem] xl:flex-[0.58_1_0]"
                    >
                      <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                        {newsItems[0]?.headline ?? (hasSnapshot ? 'No news headlines available.' : 'News unavailable.')}
                      </p>
                    </TelemetryCard>

                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
                      enabled={marketEnabled}
                      isCompact
                      attentionTier={attentionTiers.market}
                      attentionStaggerMs={attentionStagger.market}
                      className="hidden w-full xl:flex xl:min-h-[3.75rem] xl:flex-[0.58_1_0]"
                    />
                  </>
                ) : (
                  <>
                <TelemetryCard
                  title="Weather"
                  icon={CloudSun}
                  primaryTemperatureF={primaryTemperatureF}
                  weatherCondition={weatherInfo.condition}
                  ledState={weatherLedState}
                  onRefresh={() => handleRefreshConnector('weather')}
                  refreshDisabled={isRefreshingAll}
                  statusMessage={weatherStatusMessage}
                  isCompact={isConsoleCompact}
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
                  isCompact={isConsoleCompact}
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
                  </>
                )}
              </div>
            </div>

            {/* COLUMN 2: CENTER REACTOR */}
            <div
              className={`hud-center-column ${useFullscreenOverviewLayout ? 'order-1 xl:order-2 xl:gap-6' : 'order-1'} relative z-[var(--z-core-logo)] min-w-0 items-center gap-4 ${wingTransition} ${isDormant ? centerColumnDormantClasses : centerColumnActiveClasses}`}
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
                      ? [briefing.synthesisProvider, briefing.synthesisProfile]
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
                      isAssistantQuerying={isAssistantQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      isLocalModelLoaded={isLocalModelLoaded}
                      isTelemetryCollecting={isTelemetryCollecting}
                      isOuterSegmentSurging={isCompatibilitySegmentSurging}
                      className={logoSizeClass}
                    />
                  </div>
                  <div
                    className={`absolute left-1/2 top-full flex -translate-x-1/2 flex-col items-center whitespace-nowrap transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                      isDormant ? 'mt-7 xl:mt-9' : 'mt-2'
                    }`}
                  >
                    <VoiceSignalGlyph
                      step={activeStep}
                      status={logoStatus}
                      isSpeaking={isSpeaking}
                      activeTtsEngine={resolvedTtsEngine}
                      systemLoadThrottled={resolvedSystemThrottled}
                      isAssistantQuerying={isAssistantQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      loadingDisplayName={loadingDisplayName}
                    />
                    <LocalModelControl
                      profile={activeLocalModel}
                      loadingProfile={loadingLocalProfile}
                      busy={localLifecycleBusy}
                      onUnload={unloadLocalModel}
                    />
                    <div
                      className={`mt-2 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                        isDormant
                          ? 'pointer-events-auto translate-y-0 opacity-100'
                          : 'pointer-events-none -translate-y-1 opacity-0'
                      }`}
                    >
                      <StandbyActions
                        onStartApex={() => void handleStartApex()}
                        onStartWithBriefing={() => void handleStartWithBriefing()}
                        disabled={preflight.isChecking}
                      />
                    </div>
                    {activated ? (
                      <div className="mt-2 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]">
                        <div className="flex w-max flex-nowrap items-center justify-center gap-2">
                          <button
                            type="button"
                            onClick={handleRefreshAll}
                            disabled={isRefreshingAll}
                            data-slot="refresh-all-trigger"
                            className="group hud-command-surface inline-flex items-center rounded-md border border-white/10 bg-white/5 px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-text)] transition-colors duration-300 hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40 sm:text-[11px]"
                          >
                            {isRefreshingAll ? (
                              '[ REFRESHING… ]'
                            ) : (
                              <>
                                <span className="group-hover:hidden group-focus-visible:hidden">[ REFRESH ALL ]</span>
                                <span className="hidden group-hover:inline group-focus-visible:inline">&gt; REFRESH ALL</span>
                              </>
                            )}
                          </button>
                          <BriefingGenerateControl
                            mainDisabled={briefingControlsBusy || !briefingModeAvailable || !hasSnapshot}
                            refreshDisabled={briefingControlsBusy || !briefingModeAvailable}
                            busy={briefingControlsBusy}
                            onGenerate={() => void handleGenerateBriefing()}
                            onRefreshAndGenerate={() => void handleRefreshAllAndGenerate()}
                          />
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`hud-wing-column order-3 flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useFullscreenOverviewLayout ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${isConsoleCompact ? 'xl:overflow-y-auto xl:pr-1 scrollbar-thin' : ''} ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
            >
              <TelemetryCard
                title="Inbox"
                icon={Mail}
                ledState={emailLedState}
                onRefresh={() => handleRefreshConnector('email')}
                refreshDisabled={isRefreshingAll}
                statusMessage={emailStatusMessage}
                isCompact={isConsoleCompact}
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
                isCompact={isConsoleCompact}
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
                isCompact={isConsoleCompact}
                compactValue={remindersCompactValue}
                attentionTier={attentionTiers.reminders}
                attentionStaggerMs={attentionStagger.reminders}
                className={rightTelemetryPanelClass}
                role="region"
                aria-label="Active reminders"
                data-slot="reminders-card"
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

      {!isDormant && Boolean(showAskApexBar) ? (
        <div className="relative z-[var(--z-bento-hud)] mx-auto mt-4 w-full max-w-xl">
          <button type="button" onClick={() => setWorkspace('cortex')} className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[#7EB3FF] hover:text-white">Open Cortex</button>
          <AskApexBar
            activeProfile={agentProfile}
            onSubmit={handleOverviewSubmit}
            profilesStatus={profilesStatus}
            isSubmitting={isAssistantQuerying}
          />
        </div>
      ) : null}
          </>
        ) : (
          <CortexWorkspace
            activeProfile={agentProfile}
            cloudEffort={cloudEffort}
            devModeActive={devModeActive}
            askApexEnabled={Boolean(askApexEnabled)}
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            history={assistantHistory}
            latestTrace={assistantLatestTrace}
            error={assistantError}
            contextUsage={assistantContextUsage}
            commands={localCommands}
            armedToolScope={armedLocalToolScope}
            onArmedToolScopeChange={setArmedLocalToolScope}
            isQuerying={isAssistantQuerying}
            lifecycleBusy={localLifecycleBusy}
            lifecycleActionPending={isLocalModelActionPending}
            verifyingCloudProfile={verifyingCloudProfile}
            onLoadLocalModel={loadLocalModel}
            onUnloadLocalModel={unloadLocalModel}
            onVerifyCloudProfile={verifyCloudProfile}
            snapshotAttached={snapshotAttached}
            snapshotAvailable={telemetry.snapshot !== null}
            onSnapshotAttachedChange={setSnapshotAttached}
            onProfileChange={handleProfileChange}
            onEffortChange={handleEffortChange}
            onGoogleSearchChange={handleGoogleSearchChange}
            neofelisGoogleSearchEnabled={neofelisGoogleSearchEnabled}
            onGoogleMapsChange={handleGoogleMapsChange}
            neofelisGoogleMapsEnabled={neofelisGoogleMapsEnabled}
            onDelphinusXSearchChange={handleDelphinusXSearchChange}
            delphinusXSearchEnabled={delphinusXSearchEnabled}
            onOrcinusXSearchChange={handleOrcinusXSearchChange}
            orcinusXSearchEnabled={orcinusXSearchEnabled}
            onSubmit={handleOverviewSubmit}
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
