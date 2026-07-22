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
  type ComponentProps,
  type CSSProperties,
  type ReactElement,
} from 'react'

import { ApexLogo } from './components/ApexLogo'
import { LocalModelControl } from './components/LocalModelControl'
import { CelestialBackground } from './components/CelestialBackground'
import { ConsoleTray } from './components/ConsoleTray'
import { BriefingDigest } from './components/BriefingDigest'
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
import { useMarketData } from './hooks/useMarketData'
import { usePreflight } from './hooks/usePreflight'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import { useTelemetrySnapshot } from './hooks/useTelemetrySnapshot'
import { API_ENDPOINTS } from './lib/api'
import { resolveAttentionStaggerMs, resolveTelemetryAttentionTier } from './lib/attentionTier'
import { moduleReasonLabel, resolveModuleLedState } from './lib/moduleTelemetry'
import { resolveWeatherFromModule } from './lib/weatherTelemetry'
import type { AssistantProfile } from './types/telemetry'
import type { SettingsResponse } from './types/settings'

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

function getMediaQueryMatch(query: string): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }

  return window.matchMedia(query).matches
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => getMediaQueryMatch(query))

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }

    const mediaQueryList = window.matchMedia(query)
    const updateMatch = (): void => {
      setMatches(mediaQueryList.matches)
    }

    updateMatch()
    mediaQueryList.addEventListener('change', updateMatch)

    return () => {
      mediaQueryList.removeEventListener('change', updateMatch)
    }
  }, [query])

  return matches
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

interface ParsedCalendarEvent {
  summary: string
  start: string
}

function parseCalendarTelemetry(
  calendarText: string,
): { count: number; items: ParsedCalendarEvent[] } {
  if (!calendarText || calendarText.includes('No upcoming events')) {
    return { count: 0, items: [] }
  }

  const stripped = calendarText
    .replace(/^Calendar Telemetry\s*\(48h\)\s*:\s*/i, '')
    .trim()
  if (!stripped || /no upcoming events/i.test(stripped)) {
    return { count: 0, items: [] }
  }

  const matches = [...stripped.matchAll(/'([^']+)'\s+at\s+([^|]+)/g)]
  const items = matches.map((m) => ({
    summary: m[1],
    start: m[2].trim(),
  }))
  return { count: items.length, items }
}

const VALID_ASSISTANT_PROFILES: readonly AssistantProfile[] = [
  'comet',
  'nova',
  'pulsar',
  'lynx',
  'acinonyx',
  'neofelis',
]

function isAssistantProfile(value: string): value is AssistantProfile {
  return (VALID_ASSISTANT_PROFILES as readonly string[]).includes(value)
}

export default function App(): ReactElement {
  const [reminderPulseCount, setReminderPulseCount] = useState(0)
  const [agentProfile, setAgentProfile] = useState<AssistantProfile>('comet')
  const [activeTab, setActiveTab] = useState<'assistant' | 'reminders'>('assistant')
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const settingsButtonRef = useRef<HTMLButtonElement>(null)
  const isShowcaseDesktop = useMediaQuery('(min-width: 1280px) and (min-height: 821px)')

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const apexData = useApexData()
  const {
    activeReminders,
    demoModeActive,
    devModeActive,
    askApexEnabled,
    marketEnabled,
    defaultProfile,
    synthesisStrategy: configuredSynthesisStrategy,
    synthesisProfile: configuredSynthesisProfile,
    refreshReminders,
    markReminderAsRead,
    applyBootSettings,
  } = apexData
  const { data: marketData, isLoading: isMarketLoading } = useMarketData(marketEnabled)

  const { activated, activate } = useAppActivation()
  const preflight = usePreflight()
  const telemetry = useTelemetrySnapshot()
  const briefing = useBriefingPipeline()

  const showAskApexBar = activated && Boolean(askApexEnabled)

  const {
    assistantHistory,
    isAssistantQuerying,
    isAssistantOpen,
    assistantLatestTrace,
    assistantError,
    profilesStatus,
    profilesStatusHydrated,
    queryAssistant,
    unloadLocalModel,
    clearAssistantChat,
    setAssistantOpen,
  } = useApexAssistant(true)

  // Synchronize the active profile with backend defaults when idle (not mid-query).
  useEffect(() => {
    if (isAssistantQuerying) {
      return
    }
    if (defaultProfile && isAssistantProfile(defaultProfile)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Mirrors backend boot/settings config into selectable profile state.
      setAgentProfile(defaultProfile)
    }
  }, [defaultProfile, isAssistantQuerying])

  const handleSettingsApplied = useCallback(
    (response: SettingsResponse) => {
      applyBootSettings({
        askApexEnabled: response.settings.assistant.enabled,
        defaultProfile: response.settings.assistant.default_profile,
        marketEnabled: response.settings.features.market,
      })
    },
    [applyBootSettings],
  )

  const { pipelineState, isSpeaking, active_tts_engine, system_load_throttled } = briefing
  const resolvedTtsEngine = pipelineState?.active_tts_engine ?? active_tts_engine
  const resolvedSystemThrottled =
    pipelineState?.system_load_throttled ?? system_load_throttled
  const liveSynthesis = pipelineState?.synthesis
  const resolvedSynthesisProvider = liveSynthesis?.provider ?? briefing.synthesisProvider
  const resolvedSynthesisProfile = liveSynthesis?.profile ?? briefing.synthesisProfile
  const resolvedSynthesisReason = liveSynthesis?.fallback_reason ?? briefing.synthesisFallbackReason

  const activeStep = pipelineState?.step ?? null
  const isBriefingRunning = briefing.status === 'loading'

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
  // Expanded assistant sessions become a right rail on desktop. Smaller
  // and height-constrained viewports keep the existing bottom tray behavior.
  const useRightRailConsole = isShowcaseDesktop
  const isConsoleCompact = isAssistantOpen && !isDormant && useRightRailConsole

  const wingTransition =
    'transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)]'
  const wingHeightClass = useRightRailConsole ? 'xl:h-full' : 'h-auto'
  const leftWingDormantClasses = useRightRailConsole
    ? 'opacity-0 -translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
    : 'hidden'
  const leftWingActiveClasses = useRightRailConsole
    ? 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
    : 'opacity-100 translate-x-0 scale-100 pointer-events-auto max-w-full flex-none overflow-visible'
  const rightWingDormantClasses = useRightRailConsole
    ? 'opacity-0 translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
    : 'hidden'
  const rightWingActiveClasses = useRightRailConsole
    ? 'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
    : 'opacity-100 translate-x-0 scale-100 pointer-events-auto max-w-full flex-none overflow-visible'
  const centerColumnDormantClasses = useRightRailConsole
    ? 'h-full min-h-0 flex flex-col justify-center xl:max-w-full xl:flex-1'
    : 'h-auto min-h-0 flex flex-col justify-center'
  const centerColumnActiveClasses = useRightRailConsole
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
    void fetch(API_ENDPOINTS.voiceSpeak, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'APEX online. Ready for operations.' }),
    }).catch(() => {
      // Activation voice cue is best-effort; ignore delivery failures.
    })
  }, [preflight, activate, telemetry])

  const handleStartWithBriefing = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('activate_with_briefing', {
      synthesis_profile: configuredSynthesisProfile,
      involves_cloud: configuredSynthesisStrategy === 'cloud',
    })
    if (resolution !== 'proceed') {
      return
    }

    activate()
    await briefing.triggerSynthesis()
    void telemetry.loadLatest()
  }, [preflight, configuredSynthesisProfile, configuredSynthesisStrategy, activate, briefing, telemetry])

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
  const weatherPanelLayoutClass = useRightRailConsole
    ? 'xl:flex-[0.5_1_0] xl:min-h-0'
    : 'hud-panel-natural min-h-[8rem]'
  const eventsPanelLayoutClass = useRightRailConsole
    ? 'xl:flex-[1.5_1_0] xl:min-h-0'
    : 'hud-panel-natural min-h-[11rem]'
  const marketPanelLayoutClass = useRightRailConsole
    ? 'xl:flex-[1_1_0]'
    : 'hud-panel-natural min-h-[12rem]'
  const rightTelemetryPanelClass = isConsoleCompact
    ? 'xl:hidden'
    : useRightRailConsole
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

  const handleReminderSaved = (): void => {
    setReminderPulseCount((prev) => prev + 1)
  }

  const handleGenerateBriefing = useCallback(async (): Promise<void> => {
    const resolution = await preflight.requestOperation('generate_briefing', {
      synthesis_profile: configuredSynthesisProfile,
      involves_cloud: configuredSynthesisStrategy === 'cloud',
    })
    if (resolution !== 'proceed') {
      return
    }
    await briefing.triggerSynthesis()
    void telemetry.loadLatest()
  }, [preflight, configuredSynthesisProfile, configuredSynthesisStrategy, briefing, telemetry])

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
  const calendarInfo = parseCalendarTelemetry(calendarModule?.display_text ?? '')

  // Shared insight list for the BriefingDigest panel.
  const combinedInsights = [
    ...activeReminders.map((r) => `Reminder: ${r.note}`),
    ...briefing.insights,
  ]

  const weatherCompactValue = primaryTemperatureF != null ? `${primaryTemperatureF}°` : null
  const weatherConditionCompactValue =
    primaryTemperatureF != null && weatherBody.trim().length > 0
      ? `${primaryTemperatureF}°, ${weatherBody}`
      : weatherCompactValue
  const eventsCompactValue = hasSnapshot
    ? calendarInfo.count > 0
      ? `${calendarInfo.count} events`
      : 'No events'
    : null
  const inboxCompactValue = hasSnapshot ? `${emailInfo.count} unread` : null
  const newsCompactValue = hasSnapshot ? `${newsItems.length} headlines` : null
  const remindersCompactValue = `${pendingReminderCount} pending`
  const queryAssistantWithContext = useCallback(
    async (prompt: string, profile: AssistantProfile): Promise<void> => {
      const resolution = await preflight.requestOperation('assistant_query', {
        synthesis_profile: profile,
        involves_cloud: profile === 'comet' || profile === 'nova' || profile === 'pulsar',
      })
      if (resolution !== 'proceed') {
        return
      }
      await queryAssistant(prompt, profile, {
        snapshotId: telemetry.snapshot?.snapshot_id ?? null,
      })
    },
    [preflight, queryAssistant, telemetry.snapshot?.snapshot_id],
  )

  const consoleTrayProps = {
    isExpanded: isAssistantOpen,
    setExpanded: setAssistantOpen,
    activeTab,
    setActiveTab,
    assistantHistory,
    isAssistantQuerying,
    assistantLatestTrace,
    assistantError,
    profilesStatus,
    profilesStatusHydrated,
    queryAssistant: queryAssistantWithContext,
    clearAssistantChat,
    activeProfile: agentProfile,
    setActiveProfile: setAgentProfile,
    askApexEnabled: Boolean(showAskApexBar),
    activeReminders,
    markReminderAsRead: handleMarkReminderRead,
    refreshReminders,
    onReminderSaved: handleReminderSaved,
  } satisfies ComponentProps<typeof ConsoleTray>

  return (
    <main
      className={`hud-app-shell ${useRightRailConsole ? 'hud-layout-fullscreen' : 'hud-layout-compact'} relative isolate flex h-dvh w-full min-h-0 flex-col overflow-x-hidden bg-[var(--hud-bg)] p-4 md:p-6`}
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
        <header className="hud-header relative pointer-events-none mb-4 flex h-16 w-full shrink-0 select-none flex-nowrap items-center">
          <SystemDiagnostics
            diagnostics={diagnostics}
            diagnosticsStatus={diagnosticsStatus}
            status={briefing.status === 'idle' && activated ? (hasSnapshot ? 'success' : isRefreshingAll ? 'loading' : 'idle') : briefing.status}
            confidenceScore={telemetry.snapshot?.sync_health_score ?? briefing.confidenceScore}
            failedConnectors={telemetry.snapshot?.failed_connectors ?? briefing.failedConnectors}
            connectorHealth={telemetry.snapshot?.connector_health ?? briefing.connectorHealth}
            demoModeActive={demoModeActive}
            devModeActive={devModeActive}
            synthesisProvider={resolvedSynthesisProvider}
            synthesisProfile={resolvedSynthesisProfile}
            synthesisFallbackReason={resolvedSynthesisReason}
            onOpenSettings={() => setIsSettingsOpen(true)}
            settingsButtonRef={settingsButtonRef}
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

        <div className={`hud-body-layout flex w-full flex-col gap-4 overflow-visible ${useRightRailConsole ? 'xl:h-full xl:min-h-0 xl:flex-1 xl:flex-row xl:overflow-hidden xl:gap-6' : 'flex-none'}`}>
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`hud-wing-column ${useRightRailConsole ? 'order-2 xl:order-1' : 'order-2'} flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useRightRailConsole ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <div className={`flex min-h-0 flex-col ${wingGapClass} xl:flex ${useRightRailConsole ? 'xl:flex-1' : ''}`}>
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
                          {calendarInfo.count > 0 && (
                            <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
                              {calendarInfo.count} Upcoming
                            </p>
                          )}
                          {calendarInfo.items.length > 0 ? (
                            <ul className="list-fade-mask min-h-0 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                              {calendarInfo.items.slice(0, 3).map((item, index) => (
                                <li
                                  key={`${item.summary}-${item.start}-${index}`}
                                  className="flex items-start justify-between gap-3"
                                >
                                  <span className="flex min-w-0 items-start gap-2">
                                    <span className="hud-log-index">
                                      {String(index).padStart(2, '0')}
                                    </span>
                                    <span className="break-words text-sm text-zinc-200">
                                      {item.summary}
                                    </span>
                                  </span>
                                  <span className="shrink-0 font-mono text-xs text-zinc-500">
                                    {item.start}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          ) : hasSnapshot ? (
                            <p className="text-sm text-[color:var(--hud-muted-text)]">
                              No upcoming events.
                            </p>
                          ) : (
                            <p className="text-sm text-[color:var(--hud-muted-text)]">
                              Schedule unavailable.
                            </p>
                          )}
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
                      {calendarInfo.count > 0 && (
                        <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
                          {calendarInfo.count} Upcoming
                        </p>
                      )}
                      {calendarInfo.items.length > 0 ? (
                        <ul className="list-fade-mask min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                          {calendarInfo.items.map((item, index) => (
                            <li
                              key={`${item.summary}-${item.start}-${index}`}
                              className="flex items-start justify-between gap-3"
                            >
                              <span className="flex min-w-0 items-start gap-2">
                                <span className="hud-log-index">
                                  {String(index).padStart(2, '0')}
                                </span>
                                <span className="break-words text-sm text-zinc-200">
                                  {item.summary}
                                </span>
                              </span>
                              <span className="shrink-0 font-mono text-xs text-zinc-500">
                                {item.start}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : hasSnapshot ? (
                        <p className="text-sm text-[color:var(--hud-muted-text)]">
                          No upcoming events.
                        </p>
                      ) : (
                        <p className="text-sm text-[color:var(--hud-muted-text)]">
                          Schedule unavailable.
                        </p>
                      )}
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
              className={`hud-center-column ${useRightRailConsole ? 'order-1 xl:order-2 xl:gap-6' : 'order-1'} relative z-[var(--z-core-logo)] min-w-0 items-center gap-4 ${wingTransition} ${isDormant ? centerColumnDormantClasses : centerColumnActiveClasses}`}
            >
              {/* Ambient Logo Glow Projector */}
              <div
                className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-12 h-[380px] w-[380px] rounded-full blur-[120px] opacity-10 mix-blend-screen"
                style={{ background: 'rgba(var(--glow-color), 0.15)' }}
                aria-hidden
              />
              <div className={`shrink-0 flex flex-col ${digestWrapperClass}`}>
                <BriefingDigest
                  insights={combinedInsights}
                  briefingText={briefing.briefing}
                  status={briefing.status}
                  activated={activated}
                  isLoading={briefing.status === 'loading'}
                  onGenerateBriefing={handleGenerateBriefing}
                  generateDisabled={isBriefingRunning}
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
                      busy={isAssistantQuerying || liveSynthesis?.phase === 'generating'}
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
                    <div
                      className={`mt-2 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                        activated
                          ? 'pointer-events-auto translate-y-0 opacity-100'
                          : 'pointer-events-none -translate-y-1 opacity-0'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={handleRefreshAll}
                        disabled={isRefreshingAll}
                        data-slot="refresh-all-trigger"
                        className="hud-command-surface inline-flex rounded-md border border-white/10 bg-white/5 px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-text)] transition-colors duration-300 hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {isRefreshingAll ? '[ REFRESHING… ]' : '[ REFRESH ALL ]'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`hud-wing-column order-3 flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useRightRailConsole ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${isConsoleCompact ? 'xl:overflow-y-auto xl:pr-1 scrollbar-thin' : ''} ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
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

              <div className={`${useRightRailConsole ? (isAssistantOpen ? 'hidden h-full min-h-0 xl:flex xl:mt-auto' : 'hidden xl:flex xl:mt-auto') : 'hidden'}`}>
                <ConsoleTray
                  {...consoleTrayProps}
                  placement="rail"
                />
              </div>
            </div>
        </div>
      </div>

      {!isDormant && !useRightRailConsole ? (
        <div className="hud-console-bottom-tray relative z-[var(--z-bento-hud)] mt-4 flex-none shrink-0">
          <ConsoleTray
            {...consoleTrayProps}
          />
        </div>
      ) : null}

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
