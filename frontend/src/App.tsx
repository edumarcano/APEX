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
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react'

import { ApexLogo } from './components/ApexLogo'
import { CelestialBackground } from './components/CelestialBackground'
import { ConsoleTray } from './components/ConsoleTray'
import { CommandTrigger } from './components/CommandTrigger'
import { BriefingDigest } from './components/BriefingDigest'
import { MarketTickerCard } from './components/MarketTickerCard'
import { ReminderListRow } from './components/ReminderListRow'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard, type TelemetryLedState } from './components/TelemetryCard'
import { VoiceSignalGlyph } from './components/VoiceSignalGlyph'
import { useApexData } from './hooks/useApexData'
import { useApexAssistant } from './hooks/useApexAssistant'
import { useMarketData } from './hooks/useMarketData'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import {
  resolveAttentionStaggerMs,
  resolveAttentionTier,
} from './lib/attentionTier'
import type { AssistantProfile, WeatherConditionArchetype } from './types/telemetry'

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

function isBusy(status: 'idle' | 'loading' | 'success' | 'error'): boolean {
  return status === 'idle' || status === 'loading'
}

/** Mirrors the unified pipeline status into a compact per-card status LED. */
function resolveTelemetryLedState(
  status: 'idle' | 'loading' | 'success' | 'error',
): TelemetryLedState {
  if (status === 'error') return 'error'
  if (isBusy(status)) return 'loading'
  if (status === 'success') return 'live'
  return 'stale'
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
  const [agentProfile, setAgentProfile] = useState<AssistantProfile>('nova')
  const [activeTab, setActiveTab] = useState<'assistant' | 'reminders'>('assistant')
  const isShowcaseDesktop = useMediaQuery('(min-width: 1280px) and (min-height: 821px)')

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const { data: marketData, isLoading: isMarketLoading } = useMarketData()
  const apexData = useApexData()
  const {
    data,
    status,
    error,
    pipelineState,
    isSpeaking,
    activeReminders,
    demoModeActive,
    devModeActive,
    confidenceScore,
    failedConnectors,
    active_tts_engine,
    system_load_throttled,
    askApexEnabled,
    refreshReminders,
    markReminderAsRead,
    triggerSynthesis,
  } = apexData

  const showAskApexBar = status === 'success' && askApexEnabled

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
    resetAssistantSession,
    setAssistantOpen,
  } = useApexAssistant(showAskApexBar)

  // Synchronize the active profile state with the backend's configured defaults on boot
  useEffect(() => {
    const profile = data?.defaultProfile
    if (profile && isAssistantProfile(profile)) {
      setAgentProfile(profile)
    }
  }, [data?.defaultProfile])

  const resolvedTtsEngine = pipelineState?.active_tts_engine ?? active_tts_engine
  const resolvedSystemThrottled =
    pipelineState?.system_load_throttled ?? system_load_throttled

  const activeStep = pipelineState?.step ?? null
  const isProcessing =
    status === 'loading' ||
    (activeStep !== null && activeStep >= 1 && activeStep <= 3)

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
  const isLocalModelLoading = loadingLocalProfile !== null
  const isLocalModelLoaded = activeLocalModel !== null
  const loadingDisplayName = loadingLocalProfile?.display_name ?? null

  const glowColor = useMemo((): string => {
    if (status === 'error') {
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
    if (status === 'success' && !isSpeaking) {
      return isLocalModelLoaded ? '249, 115, 22' : '15, 77, 184'
    }
    if (activeStep === 3) {
      return '168, 85, 247' // Purple/magenta (logo accent)
    }
    if (status === 'loading' || activeStep === 1 || activeStep === 2) {
      return '57, 255, 136' // Green
    }
    if (isLocalModelLoaded) {
      return '249, 115, 22' // Rust orange (local model loaded)
    }
    return '15, 23, 42' // Deep Slate Blue
  }, [
    status,
    activeStep,
    isSpeaking,
    isLocalModelLoading,
    isAssistantQuerying,
    isLocalModelLoaded,
  ])

  const weatherBorderByCondition: Record<WeatherConditionArchetype, string> = {
    clear_day: '#1E6BFF',
    clear_night: '#0F4DB8',
    clouds: '#6E88AB',
    rain: '#1E6BFF',
    thunderstorm: '#7EB3FF',
  }

  const weatherCardStyle = useMemo((): CSSProperties | undefined => {
    const condition = data?.weatherCondition
    if (!condition) return undefined

    const borderColor = weatherBorderByCondition[condition]
    return { '--hud-border-color': borderColor } as CSSProperties
  }, [data?.weatherCondition])

  const hasSuccessfulData = status === 'success' && Boolean(data)
  const isTriggerLoading = status === 'loading'
  const showCommandTrigger = status === 'idle'
  const isTriggerDisabled = isProcessing
  const pendingReminderCount = activeReminders.length
  const isDormant = status === 'idle'
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

  useEffect(() => {
    const handleGlobalEnter = (event: KeyboardEvent): void => {
      if (status !== 'idle') {
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
        tagName === 'INPUT' ||
        tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return
      }

      resetAssistantSession()
      void triggerSynthesis()
    }

    window.addEventListener('keydown', handleGlobalEnter)
    return () => {
      window.removeEventListener('keydown', handleGlobalEnter)
    }
  }, [status, triggerSynthesis, resetAssistantSession])

  const cardLedState = resolveTelemetryLedState(status)
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

  const attentionTiers = useMemo(
    () => ({
      reminders: resolveAttentionTier('reminders', activeStep, status),
      weather: resolveAttentionTier('weather', activeStep, status),
      news: resolveAttentionTier('news', activeStep, status),
      events: resolveAttentionTier('events', activeStep, status),
      market: resolveAttentionTier('market', activeStep, status),
      inbox: resolveAttentionTier('inbox', activeStep, status),
      insights: resolveAttentionTier('insights', activeStep, status),
    }),
    [activeStep, status],
  )

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

  const weatherBody = (() => {
    if (hasSuccessfulData) {
      const detail = data?.weatherDetail?.trim() ?? ''
      return detail.length > 0 ? detail : 'No weather data.'
    }
    if (isBusy(status)) {
      return 'Loading weather…'
    }
    return error ?? 'Weather unavailable.'
  })()

  const primaryTemperatureF =
    hasSuccessfulData && data?.temperatureF != null ? data.temperatureF : null

  const handleMarkReminderRead = (id: number): void => {
    void markReminderAsRead(id)
  }

  const handleReminderSaved = (): void => {
    setReminderPulseCount((prev) => prev + 1)
  }

  const handleTriggerSynthesis = useCallback((): void => {
    resetAssistantSession()
    void triggerSynthesis()
  }, [resetAssistantSession, triggerSynthesis])

  const f1ScheduleTelemetryText = data?.sports?.trim() ?? ''
  const emailInfo = parseEmailTelemetry(data?.email ?? '')
  const newsItems = parseNewsTelemetry(data?.news ?? '')
  const calendarInfo = parseCalendarTelemetry(data?.calendar ?? '')

  // Shared insight list for the BriefingDigest panel.
  const combinedInsights = [
    ...(data?.activeReminders ?? []).map((r) => `Reminder: ${r.note}`),
    ...(data?.digest?.insights ?? []),
  ]

  const weatherCompactValue = primaryTemperatureF != null ? `${primaryTemperatureF}°` : null
  const weatherConditionCompactValue =
    primaryTemperatureF != null && weatherBody.trim().length > 0
      ? `${primaryTemperatureF}°, ${weatherBody}`
      : weatherCompactValue
  const eventsCompactValue =
    status === 'success'
      ? calendarInfo.count > 0
        ? `${calendarInfo.count} events`
        : 'No events'
      : null
  const inboxCompactValue = status === 'success' ? `${emailInfo.count} unread` : null
  const newsCompactValue = status === 'success' ? `${newsItems.length} headlines` : null
  const remindersCompactValue = `${pendingReminderCount} pending`

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
            status={status}
            confidenceScore={confidenceScore}
            failedConnectors={failedConnectors}
            demoModeActive={demoModeActive}
            devModeActive={devModeActive}
          />
        </header>

        <div className={`hud-body-layout flex w-full flex-col gap-4 overflow-visible ${useRightRailConsole ? 'xl:h-full xl:min-h-0 xl:flex-1 xl:flex-row xl:overflow-hidden xl:gap-6' : 'flex-none'}`}>
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`hud-wing-column ${useRightRailConsole ? 'order-2 xl:order-1' : 'order-2'} flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useRightRailConsole ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${wingGapClass} ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <div className={`flex min-h-0 flex-col ${wingGapClass} xl:flex ${useRightRailConsole ? 'xl:flex-1' : ''}`}>
                {isConsoleCompact ? (
                  <>
                    <TelemetryCard
                      title="Weather"
                      icon={CloudSun}
                      primaryTemperatureF={primaryTemperatureF}
                      weatherCondition={data?.weatherCondition}
                      ledState={cardLedState}
                      isCompact
                      compactValue={weatherConditionCompactValue}
                      attentionTier={attentionTiers.weather}
                      attentionStaggerMs={attentionStagger.weather}
                      style={weatherCardStyle}
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
                      ledState={cardLedState}
                      compactValue={eventsCompactValue}
                      attentionTier={attentionTiers.events}
                      attentionStaggerMs={attentionStagger.events}
                      className="hidden min-h-0 xl:flex xl:flex-[2.05_1_0]"
                    >
                      {isBusy(status) ? (
                        <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                          Loading schedule…
                        </p>
                      ) : (
                        <>
                          {status === 'success' && calendarInfo.count > 0 && (
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
                          ) : status === 'success' ? (
                            <p className="text-sm text-[color:var(--hud-muted-text)]">
                              No upcoming events.
                            </p>
                          ) : (
                            <p className="text-sm text-[color:var(--hud-muted-text)]">
                              {error ?? 'Schedule unavailable.'}
                            </p>
                          )}
                        </>
                      )}
                    </TelemetryCard>

                    <TelemetryCard
                      title="Inbox"
                      icon={Mail}
                      ledState={cardLedState}
                      compactValue={inboxCompactValue}
                      attentionTier={attentionTiers.inbox}
                      attentionStaggerMs={attentionStagger.inbox}
                      className="hidden min-h-0 xl:flex xl:flex-[1.2_1_0]"
                    >
                      {isBusy(status) ? (
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
                          {status === 'success' ? 'No unread emails.' : error ?? 'Inbox unavailable.'}
                        </p>
                      )}
                    </TelemetryCard>

                    <TelemetryCard
                      title="News Wire"
                      icon={Newspaper}
                      ledState={cardLedState}
                      isCompact
                      compactValue={newsCompactValue}
                      attentionTier={attentionTiers.news}
                      attentionStaggerMs={attentionStagger.news}
                      className="hidden xl:flex xl:min-h-[3.75rem] xl:flex-[0.58_1_0]"
                    >
                      <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                        {newsItems[0]?.headline ?? (status === 'success' ? 'No news headlines available.' : error ?? 'News unavailable.')}
                      </p>
                    </TelemetryCard>

                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
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
                  weatherCondition={data?.weatherCondition}
                  ledState={cardLedState}
                  isCompact={isConsoleCompact}
                  compactValue={weatherBody}
                  attentionTier={attentionTiers.weather}
                  attentionStaggerMs={attentionStagger.weather}
                  style={weatherCardStyle}
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
                  ledState={cardLedState}
                  isCompact={isConsoleCompact}
                  compactValue={eventsCompactValue}
                  attentionTier={attentionTiers.events}
                  attentionStaggerMs={attentionStagger.events}
                  className={`min-h-0 ${eventsPanelLayoutClass}`}
                >
                  {isBusy(status) ? (
                    <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                      Loading schedule…
                    </p>
                  ) : (
                    <>
                      {status === 'success' && calendarInfo.count > 0 && (
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
                      ) : status === 'success' ? (
                        <p className="text-sm text-[color:var(--hud-muted-text)]">
                          No upcoming events.
                        </p>
                      ) : (
                        <p className="text-sm text-[color:var(--hud-muted-text)]">
                          {error ?? 'Schedule unavailable.'}
                        </p>
                      )}
                    </>
                  )}
                </TelemetryCard>

                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
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
                  briefingText={data?.briefing ?? ''}
                  status={status}
                  isLoading={isTriggerLoading}
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
                      status={status}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      isAssistantQuerying={isAssistantQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      isLocalModelLoaded={isLocalModelLoaded}
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
                      status={status}
                      isSpeaking={isSpeaking}
                      activeTtsEngine={resolvedTtsEngine}
                      systemLoadThrottled={resolvedSystemThrottled}
                      isAssistantQuerying={isAssistantQuerying}
                      isLocalModelLoading={isLocalModelLoading}
                      loadingDisplayName={loadingDisplayName}
                    />
                    <div
                      className={`mt-2 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                        showCommandTrigger
                          ? 'pointer-events-auto translate-y-0 opacity-100'
                          : 'pointer-events-none -translate-y-1 opacity-0'
                      }`}
                    >
                      <CommandTrigger
                        onClick={handleTriggerSynthesis}
                        disabled={isTriggerDisabled}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`hud-wing-column order-3 flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} ${useRightRailConsole ? 'xl:min-h-0 xl:flex xl:flex-col' : ''} ${wingGapClass} ${isConsoleCompact ? 'xl:overflow-y-auto xl:pr-1 scrollbar-thin' : ''} ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
            >
              <TelemetryCard
                title="Inbox"
                icon={Mail}
                ledState={cardLedState}
                isCompact={isConsoleCompact}
                compactValue={inboxCompactValue}
                attentionTier={attentionTiers.inbox}
                attentionStaggerMs={attentionStagger.inbox}
                className={rightTelemetryPanelClass}
              >
                {isBusy(status) ? (
                  <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                    Loading inbox…
                  </p>
                ) : (
                  <>
                    {status === 'success' && emailInfo.count > 0 && (
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
                    ) : status === 'success' ? (
                      <p className="text-sm text-[color:var(--hud-muted-text)]">
                        No unread emails.
                      </p>
                    ) : (
                      <p className="text-sm text-[color:var(--hud-muted-text)]">
                        {error ?? 'Inbox unavailable.'}
                      </p>
                    )}
                  </>
                )}
              </TelemetryCard>

              <TelemetryCard
                title="News Wire"
                icon={Newspaper}
                ledState={cardLedState}
                isCompact={isConsoleCompact}
                compactValue={newsCompactValue}
                attentionTier={attentionTiers.news}
                attentionStaggerMs={attentionStagger.news}
                className={rightTelemetryPanelClass}
              >
                {isBusy(status) ? (
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
                ) : status === 'success' ? (
                  <p className="text-sm text-[color:var(--hud-muted-text)]">
                    No news headlines available.
                  </p>
                ) : (
                  <p className="text-sm text-[color:var(--hud-muted-text)]">
                    {error ?? 'News unavailable.'}
                  </p>
                )}
              </TelemetryCard>

              <TelemetryCard
                title="Reminders"
                icon={CheckSquare}
                ledState={cardLedState}
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
                  placement="rail"
                  isExpanded={isAssistantOpen}
                  setExpanded={setAssistantOpen}
                  activeTab={activeTab}
                  setActiveTab={setActiveTab}
                  assistantHistory={assistantHistory}
                  isAssistantQuerying={isAssistantQuerying}
                  assistantLatestTrace={assistantLatestTrace}
                  assistantError={assistantError}
                  profilesStatus={profilesStatus}
                  profilesStatusHydrated={profilesStatusHydrated}
                  queryAssistant={queryAssistant}
                  unloadLocalModel={unloadLocalModel}
                  clearAssistantChat={clearAssistantChat}
                  activeProfile={agentProfile}
                  setActiveProfile={setAgentProfile}
                  askApexEnabled={Boolean(showAskApexBar)}
                  activeReminders={activeReminders}
                  markReminderAsRead={handleMarkReminderRead}
                  refreshReminders={refreshReminders}
                  onReminderSaved={handleReminderSaved}
                />
              </div>
            </div>
        </div>
      </div>

      {!isDormant && !useRightRailConsole ? (
        <div className="hud-console-bottom-tray relative z-[var(--z-bento-hud)] mt-4 flex-none shrink-0">
          <ConsoleTray
            isExpanded={isAssistantOpen}
            setExpanded={setAssistantOpen}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            assistantHistory={assistantHistory}
            isAssistantQuerying={isAssistantQuerying}
            assistantLatestTrace={assistantLatestTrace}
            assistantError={assistantError}
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            queryAssistant={queryAssistant}
            unloadLocalModel={unloadLocalModel}
            clearAssistantChat={clearAssistantChat}
            activeProfile={agentProfile}
            setActiveProfile={setAgentProfile}
            askApexEnabled={Boolean(showAskApexBar)}
            activeReminders={activeReminders}
            markReminderAsRead={handleMarkReminderRead}
            refreshReminders={refreshReminders}
            onReminderSaved={handleReminderSaved}
          />
        </div>
      ) : null}
    </main>
  )
}
