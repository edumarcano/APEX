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
import { VocalOrb } from './components/VocalOrb'
import { useApexData } from './hooks/useApexData'
import { useApexAssistant } from './hooks/useApexAssistant'
import { useMarketData } from './hooks/useMarketData'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
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
  const [lastBriefingTime, setLastBriefingTime] = useState<string | null>(null)
  const [prevStatus, setPrevStatus] = useState<string>('idle')
  const [agentProfile, setAgentProfile] = useState<AssistantProfile>('nova')
  const [activeTab, setActiveTab] = useState<'assistant' | 'reminders'>('assistant')

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const { data: marketData, isLoading: isMarketLoading } = useMarketData()
  const apexData = useApexData()
  const {
    data,
    status,
    error,
    pipelineState,
    isPipelinePolling,
    isSpeaking,
    activeReminders,
    demoModeActive,
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
  const glowColor = useMemo((): string => {
    if (status === 'error') {
      return '220, 38, 38' // Red
    }
    if (activeStep === 4) {
      return '251, 191, 36' // Gold
    }
    if (status === 'success' && !isSpeaking) {
      return '15, 77, 184' // APEX Blue
    }
    if (activeStep === 3) {
      return '168, 85, 247' // Purple/magenta (logo accent)
    }
    if (status === 'loading' || activeStep === 1 || activeStep === 2) {
      return '57, 255, 136' // Green
    }
    return '15, 23, 42' // Deep Slate Blue
  }, [status, activeStep, isSpeaking])

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
  const showCommandTrigger = status === 'idle' || status === 'loading'
  const isTriggerDisabled = isProcessing
  const pendingReminderCount = activeReminders.length
  const showPendingReminderBadge = pendingReminderCount > 0
  const isDormant = status === 'idle'
  // Expanded assistant sessions become a right rail on desktop. Smaller
  // viewports keep the existing bottom tray behavior.
  const isConsoleCompact = isAssistantOpen && !isDormant

  const wingTransition =
    'transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)]'
  const wingHeightClass = 'xl:h-full'
  const leftWingDormantClasses =
    'opacity-0 -translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const leftWingActiveClasses =
    'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
  const rightWingDormantClasses =
    'opacity-0 translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const rightWingActiveClasses =
    'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1 overflow-visible'
  const centerColumnDormantClasses = 'h-full min-h-0 flex flex-col justify-center xl:max-w-full xl:flex-1'
  const centerColumnActiveClasses = `h-full min-h-0 flex flex-col ${
    isConsoleCompact ? 'justify-start pt-2 xl:pt-3' : 'justify-start pt-0'
  } xl:max-w-[33.33%] xl:flex-1 xl:min-h-0`

  // The logo is always visible and the insights panel stays mounted while the
  // desktop console opens in the right column.
  const showDigest = !isDormant
  const digestWrapperClass = [
    'transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu min-h-0 w-full',
    showDigest
      ? 'max-h-[220px] xl:max-h-[240px] opacity-100 mb-3 xl:mb-4 overflow-visible'
      : 'max-h-0 opacity-0 mb-0 overflow-hidden pointer-events-none',
  ].join(' ')

  const logoShellClass = isConsoleCompact ? 'min-h-0 flex-1 py-1 xl:py-0' : 'shrink-0 py-4 xl:py-0'

  const largeLogoWrapperClass = [
    'transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu flex flex-col items-center opacity-100 scale-100',
    isDormant
      ? 'h-64 justify-center xl:h-auto xl:flex-1'
      : isConsoleCompact
        ? 'h-full min-h-0 justify-center'
        : 'h-72 justify-center xl:h-80',
  ].join(' ')

  const logoSizeClass = isConsoleCompact
    ? 'h-full max-h-[clamp(9rem,min(22vw,30vh),19rem)] w-auto'
    : 'h-48 w-auto sm:h-56 xl:h-64'

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

  // Load initial last briefing time from history ledger
  useEffect(() => {
    let active = true
    const fetchHistory = async (): Promise<void> => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/v1/briefings/history')
        if (!response.ok) return
        const body: unknown = await response.json()
        if (!active) return

        if (Array.isArray(body) && body.length > 0) {
          const first = body[0]
          if (first && typeof first === 'object' && 'timestamp' in first) {
            const ts = first.timestamp
            if (typeof ts === 'string') {
              const date = new Date(ts)
              const formatted = date.toLocaleTimeString([], {
                hour: 'numeric',
                minute: '2-digit',
              })
              setLastBriefingTime(formatted)
            }
          }
        }
      } catch (err) {
        console.error('Failed to fetch briefing history:', err)
      }
    }
    void fetchHistory()
    return () => {
      active = false
    }
  }, [])

  // Cache last briefing time locally on successful briefing trigger
  useEffect(() => {
    if (status === 'success' && prevStatus === 'loading') {
      const now = new Date()
      const formatted = now.toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      })
      setLastBriefingTime(formatted)

    }
    setPrevStatus(status)
  }, [status, prevStatus])

  const cardLedState = resolveTelemetryLedState(status)
  const wingGapClass = isConsoleCompact ? 'gap-3' : 'gap-4'
  const marketDimmed = activeStep === 1 || activeStep === 2
  const weatherDimmed = activeStep === 1
  const scheduleDimmed = activeStep === 1 || activeStep === 2
  const staggerTransition =
    'transition-opacity duration-700 ease-in-out'

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

  const scheduleBody = (() => {
    if (hasSuccessfulData) {
      const calendar = data?.calendar?.trim() ?? ''
      return calendar.length > 0 ? calendar : 'No schedule entries.'
    }
    if (isBusy(status)) {
      return 'Loading schedule…'
    }
    return error ?? 'Schedule unavailable.'
  })()

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

  // Shared insight list for the BriefingDigest panel.
  const combinedInsights = [
    ...(data?.activeReminders ?? []).map((r) => `Reminder: ${r.note}`),
    ...(data?.digest?.insights ?? []),
  ]

  const weatherCompactValue = primaryTemperatureF != null ? `${primaryTemperatureF}°` : null
  const eventsCompactValue =
    scheduleBody.length > 28 ? `${scheduleBody.slice(0, 28)}…` : scheduleBody
  const inboxCompactValue = status === 'success' ? `${emailInfo.count} unread` : null
  const newsCompactValue = status === 'success' ? `${newsItems.length} headlines` : null
  const remindersCompactValue = `${pendingReminderCount} pending`
  const reactorStatusLabel =
    pipelineState?.label ??
    (status === 'success'
      ? 'Synthesis complete'
      : status === 'loading'
        ? 'Synchronizing'
        : status === 'error'
          ? 'Attention required'
          : 'Standby')
  const reactorHealthLabel =
    status === 'error'
      ? 'Health degraded'
      : failedConnectors.length > 0
        ? `${failedConnectors.length} connector alert`
        : `${Math.round(confidenceScore)}% confidence`
  const reactorBriefingLabel = lastBriefingTime
    ? `Last briefing ${lastBriefingTime}`
    : 'No briefing logged'

  return (
    <main
      className="relative isolate flex h-dvh w-full min-h-0 flex-col overflow-hidden bg-[var(--hud-bg)] p-4 md:p-6"
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

      <div className="relative z-[var(--z-bento-hud)] flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="relative pointer-events-none flex h-16 w-full shrink-0 select-none flex-nowrap items-center justify-between gap-4 mb-4">
          {/* Identity Pill (Left) */}
          <div className="hud-interactive-shell hud-glass rounded-full px-4 h-11 flex items-center gap-3 shrink-0 pointer-events-auto">
            <ApexLogo
              step={activeStep}
              status={status}
              isSpeaking={isSpeaking}
              reminderPulseCount={reminderPulseCount}
              className="h-6 w-auto shrink-0"
            />
            <h1
              className={`m-0 text-lg font-extrabold tracking-widest whitespace-nowrap ${isPipelinePolling
                ? 'animate-shimmer'
                : 'text-[color:var(--hud-accent)]'
                }`}
            >
              APEX
            </h1>
            {showPendingReminderBadge && (
              <span
                className="hidden sm:inline font-mono text-[10px] uppercase tracking-widest text-amber-500/80 animate-pulse whitespace-nowrap"
                aria-live="polite"
                data-slot="pending-reminder-badge"
              >
                [{pendingReminderCount}{' '}
                {pendingReminderCount === 1 ? 'Reminder' : 'Reminders'}]
              </span>
            )}
            {demoModeActive && (
              <span
                className="hidden md:inline border border-amber-500/30 text-amber-400 bg-amber-950/20 text-[10px] px-2 py-0.5 rounded-full font-mono uppercase tracking-widest animate-[pulse_2s_ease-in-out_infinite] whitespace-nowrap"
                data-slot="demo-mode-badge"
              >
                DEMO
              </span>
            )}
          </div>

          {/* Diagnostics Pill (Right) — absorbs the former Last Briefing capsule into its expanded dropdown */}
          <div className="flex h-16 items-center shrink-0 pointer-events-auto">
            <SystemDiagnostics
              diagnostics={diagnostics}
              diagnosticsStatus={diagnosticsStatus}
              isSpeaking={isSpeaking}
              isPipelinePolling={isPipelinePolling}
              status={status}
              confidenceScore={confidenceScore}
              pipelineStep={activeStep}
              pipelineLabel={pipelineState?.label ?? null}
              failedConnectors={failedConnectors}
              lastBriefingTime={lastBriefingTime}
            />
          </div>

          {/* VocalOrb Island — absolutely centered on the header's own box so its position
              never depends on (or is thrown off by) the width of the pills either side. */}
          <div className="hud-interactive-shell hud-glass rounded-full h-11 w-11 flex items-center justify-center shrink-0 pointer-events-auto absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2">
            <VocalOrb
              isSpeaking={isSpeaking}
              activeTtsEngine={resolvedTtsEngine}
              systemLoadThrottled={resolvedSystemThrottled}
              className="h-7 w-auto"
            />
          </div>
        </header>

        <div className="flex h-full min-h-0 w-full flex-1 flex-col gap-4 overflow-hidden xl:flex-row xl:gap-6">
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} xl:min-h-0 xl:flex xl:flex-col ${wingGapClass} ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <div className={`flex min-h-0 flex-col ${wingGapClass} xl:flex xl:flex-1`}>
                {isConsoleCompact ? (
                  <>
                    <TelemetryCard
                      title="Events"
                      icon={Calendar}
                      f1TelemetryText={f1ScheduleTelemetryText}
                      ledState={cardLedState}
                      compactValue={eventsCompactValue}
                      className={`hidden min-h-0 xl:flex xl:flex-[1.35_1_0] ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
                    >
                      <p className="line-clamp-3 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                        {scheduleBody}
                      </p>
                    </TelemetryCard>

                    <TelemetryCard
                      title="Inbox"
                      icon={Mail}
                      ledState={cardLedState}
                      compactValue={inboxCompactValue}
                      className="hidden min-h-0 xl:flex xl:flex-[1.35_1_0]"
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

                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
                      isCompact
                      className={`hidden w-full xl:flex xl:min-h-[4.5rem] xl:flex-[0.82_1_0] ${staggerTransition} ${marketDimmed ? 'opacity-25' : 'opacity-100'}`}
                    />

                    <TelemetryCard
                      title="Weather"
                      icon={CloudSun}
                      primaryTemperatureF={primaryTemperatureF}
                      weatherCondition={data?.weatherCondition}
                      ledState={cardLedState}
                      isCompact
                      compactValue={weatherCompactValue}
                      style={weatherCardStyle}
                      className={`hidden xl:flex xl:min-h-[4.5rem] xl:flex-[0.82_1_0] ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
                    >
                      <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                        {weatherBody}
                      </p>
                    </TelemetryCard>

                    <TelemetryCard
                      title="News Wire"
                      icon={Newspaper}
                      ledState={cardLedState}
                      isCompact
                      compactValue={newsCompactValue}
                      className="hidden xl:flex xl:min-h-[4.5rem] xl:flex-[0.82_1_0]"
                    >
                      <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                        {newsItems[0]?.headline ?? (status === 'success' ? 'No news headlines available.' : error ?? 'News unavailable.')}
                      </p>
                    </TelemetryCard>
                  </>
                ) : (
                  <>
                    <MarketTickerCard
                      data={marketData}
                      isLoading={isMarketLoading}
                      className={`h-auto w-full shrink-0 xl:flex-none ${staggerTransition} ${marketDimmed ? 'opacity-25' : 'opacity-100'}`}
                    />

                <TelemetryCard
                  title="Weather"
                  icon={CloudSun}
                  primaryTemperatureF={primaryTemperatureF}
                  weatherCondition={data?.weatherCondition}
                  ledState={cardLedState}
                  isCompact={isConsoleCompact}
                  compactValue={weatherCompactValue}
                  style={weatherCardStyle}
                  className={`${isConsoleCompact ? 'xl:min-h-[3.75rem]' : 'min-h-0 xl:flex-1 xl:min-h-0'} ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
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
                  className={`${isConsoleCompact ? 'xl:min-h-[3.75rem]' : 'min-h-0 xl:flex-1 xl:min-h-0'} ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
                >
                  <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                    {scheduleBody}
                  </p>
                </TelemetryCard>
                  </>
                )}
              </div>
            </div>

            {/* COLUMN 2: CENTER REACTOR */}
            <div
              className={`relative z-[var(--z-core-logo)] min-w-0 items-center gap-4 ${wingTransition} xl:gap-6 ${isDormant ? centerColumnDormantClasses : centerColumnActiveClasses}`}
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
                  className="w-full h-full min-h-0"
                />
              </div>

              <div className={`${logoShellClass} ${largeLogoWrapperClass}`}>
                <div className="relative flex flex-col items-center">
                  <div
                    className={`filter drop-shadow-[0_0_24px_rgba(var(--glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--glow-color),0.6)] ${isConsoleCompact ? 'h-full min-h-0' : ''} ${isDormant ? 'scale-115 xl:scale-125' : 'scale-100'}`}
                  >
                    <ApexLogo
                      step={activeStep}
                      status={status}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      className={logoSizeClass}
                    />
                  </div>
                  {isConsoleCompact ? (
                    <div className="pointer-events-none mt-4 hidden max-w-full flex-wrap items-center justify-center gap-2 px-2 xl:flex">
                      <span className="rounded-full border border-[#0F4DB8]/30 bg-[#0F4DB8]/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-[#7EB3FF] shadow-[0_0_12px_rgba(15,77,184,0.14)]">
                        {reactorStatusLabel}
                      </span>
                      <span className="rounded-full border border-emerald-400/20 bg-emerald-950/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-200/80">
                        {reactorHealthLabel}
                      </span>
                      <span className="rounded-full border border-amber-400/20 bg-amber-950/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-amber-200/80">
                        {reactorBriefingLabel}
                      </span>
                    </div>
                  ) : null}
                  <div
                    className={`absolute left-1/2 top-full -translate-x-1/2 whitespace-nowrap transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                      isDormant ? 'mt-8 xl:mt-10' : 'mt-3'
                    } ${
                      showCommandTrigger
                        ? 'pointer-events-auto opacity-100'
                        : 'pointer-events-none opacity-0'
                    }`}
                  >
                    <CommandTrigger
                      status={isTriggerLoading ? 'loading' : 'idle'}
                      onClick={handleTriggerSynthesis}
                      disabled={isTriggerDisabled}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`flex min-w-0 flex-col ${wingGapClass} ${wingHeightClass} xl:min-h-0 xl:flex xl:flex-col ${wingGapClass} ${isConsoleCompact ? 'xl:overflow-y-auto xl:pr-1 scrollbar-thin' : ''} ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
            >
              <div className={`${isAssistantOpen ? 'hidden h-full min-h-0 xl:flex' : 'hidden xl:flex'}`}>
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
                  resetAssistantSession={resetAssistantSession}
                  activeProfile={agentProfile}
                  setActiveProfile={setAgentProfile}
                  askApexEnabled={Boolean(showAskApexBar)}
                  activeReminders={activeReminders}
                  markReminderAsRead={handleMarkReminderRead}
                  refreshReminders={refreshReminders}
                  onReminderSaved={handleReminderSaved}
                />
              </div>

              <TelemetryCard
                title="Inbox"
                icon={Mail}
                ledState={cardLedState}
                isCompact={isConsoleCompact}
                compactValue={inboxCompactValue}
                className={isConsoleCompact ? 'xl:hidden' : 'flex-none xl:flex-1 xl:min-h-0'}
              >
                {isBusy(status) ? (
                  <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                    Loading inbox…
                  </p>
                ) : (
                  <>
                    {status === 'success' && emailInfo.count > 0 && (
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[color:var(--hud-accent)]">
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
                className={isConsoleCompact ? 'xl:hidden' : 'flex-none xl:flex-1 xl:min-h-0'}
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
                        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[color:var(--hud-accent)]">
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
                className={`${isConsoleCompact ? 'xl:hidden' : 'flex-none xl:flex-1 xl:min-h-0'} ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
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
      </div>

      {!isDormant ? (
        <div className="relative z-[var(--z-bento-hud)] mt-4 flex-none shrink-0 xl:hidden">
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
            resetAssistantSession={resetAssistantSession}
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
