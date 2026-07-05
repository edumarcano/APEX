import {
  Calendar,
  CheckSquare,
  Clock,
  CloudSun,
  Flag,
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

import { AskApexBar } from './components/AskApexBar'
import { ApexLogo } from './components/ApexLogo'
import { AssistantDrawer } from './components/AssistantDrawer'
import { CelestialBackground } from './components/CelestialBackground'
import { CommandTrigger } from './components/CommandTrigger'
import { BriefingDigest } from './components/BriefingDigest'
import { BriefingPanel } from './components/BriefingPanel'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderTerminal } from './components/ReminderTerminal'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VocalOrb } from './components/VocalOrb'
import { useApexData } from './hooks/useApexData'
import { useApexAssistant } from './hooks/useApexAssistant'
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

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
  const {
    assistantHistory,
    isAssistantQuerying,
    isAssistantOpen,
    assistantLatestTrace,
    assistantError,
    profilesStatus,
    queryAssistant,
    unloadLocalModel,
    resetAssistantSession,
    setAssistantOpen,
  } = useApexAssistant()
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
  const showAskApexBar = status === 'success' && askApexEnabled
  const isTriggerDisabled = isProcessing
  const pendingReminderCount = activeReminders.length
  const showPendingReminderBadge = pendingReminderCount > 0
  const isDormant = status === 'idle'

  const wingTransition =
    'transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)]'
  const leftWingDormantClasses =
    'opacity-0 -translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const leftWingActiveClasses =
    'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1'
  const rightWingDormantClasses =
    'opacity-0 translate-x-12 scale-95 pointer-events-none xl:max-w-0 xl:flex-[0_0_0%] overflow-hidden'
  const rightWingActiveClasses =
    'opacity-100 translate-x-0 scale-100 pointer-events-auto xl:max-w-full xl:flex-1'
  const centerColumnDormantClasses = 'xl:max-w-full xl:flex-1'
  const centerColumnActiveClasses = 'xl:max-w-[33.33%] xl:flex-1 xl:min-h-0'
  const briefingDigestDormantClasses =
    'max-h-0 opacity-0 overflow-hidden mb-0 scale-95 pointer-events-none'
  const briefingDigestActiveClasses =
    'max-h-[220px] xl:max-h-[240px] opacity-100 mb-4 scale-100 pointer-events-auto'

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

  const handleAgentQuery = useCallback(
    (query: string, profile: AssistantProfile): void => {
      void queryAssistant(query, profile)
    },
    [queryAssistant],
  )

  const handleAssistantFollowUp = useCallback(
    (query: string): void => {
      void queryAssistant(query, agentProfile)
    },
    [agentProfile, queryAssistant],
  )

  const handleAssistantChipSelect = useCallback(
    (query: string): void => {
      void queryAssistant(query, agentProfile)
    },
    [agentProfile, queryAssistant],
  )

  const handleTriggerSynthesis = useCallback((): void => {
    resetAssistantSession()
    void triggerSynthesis()
  }, [resetAssistantSession, triggerSynthesis])

  const f1ScheduleTelemetryText = data?.sports?.trim() ?? ''
  const emailInfo = parseEmailTelemetry(data?.email ?? '')
  const newsItems = parseNewsTelemetry(data?.news ?? '')



  const showSubtitleBar = isSpeaking && activeStep === 4

  return (
    <main
      className="relative isolate flex min-h-dvh w-full flex-col overflow-y-auto bg-[var(--hud-bg)] p-4 md:p-6 xl:h-dvh xl:overflow-hidden"
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

      <div className="relative z-[var(--z-bento-hud)] flex min-h-0 flex-1 flex-col">
        <header className="relative mb-3 grid w-full grid-cols-3 items-center border-b border-[color:var(--hud-border-color)] pb-2">
          <div className="flex items-baseline justify-self-start">
            <h1
              className={`m-0 text-2xl font-extrabold tracking-widest md:text-3xl ${isPipelinePolling
                ? 'animate-shimmer'
                : 'text-[color:var(--hud-accent)]'
                }`}
            >
              APEX
            </h1>
            <span className="mb-1 ml-3 hidden self-end text-[10px] uppercase tracking-widest text-[color:var(--hud-text)] opacity-40 sm:block">
              AUTOMATED PERSONAL ENVIRONMENT XYLEM
            </span>
          </div>
          <div className="flex justify-center justify-self-center">
            <VocalOrb
              isSpeaking={isSpeaking}
              activeTtsEngine={resolvedTtsEngine}
              systemLoadThrottled={resolvedSystemThrottled}
              className="h-12 w-auto"
            />
          </div>
          <div className="flex items-center justify-end gap-2 justify-self-end">
            {showPendingReminderBadge && (
              <span
                className="font-mono text-[10px] sm:text-[11px] uppercase tracking-widest text-amber-500/80 animate-pulse"
                aria-live="polite"
                data-slot="pending-reminder-badge"
              >
                [{pendingReminderCount}{' '}
                {pendingReminderCount === 1 ? 'Reminder' : 'Reminders'} Pending]
              </span>
            )}
            {demoModeActive && (
              <span
                className="border border-amber-500/30 text-amber-400 bg-amber-950/20 text-[10px] px-2.5 py-0.5 rounded-full font-mono uppercase tracking-widest animate-[pulse_2s_ease-in-out_infinite]"
                data-slot="demo-mode-badge"
              >
                DEMO MODE ACTIVE
              </span>
            )}
            <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-zinc-400">
              <Clock className="size-3.5 text-[#0F4DB8]" />
              <span>Last Briefing: <span className="text-[#FFFFFF]">{lastBriefingTime || 'Standby'}</span></span>
            </div>
          </div>
        </header>

        <div
          className={`w-full overflow-hidden transition-all duration-700 ease-in-out ${showSubtitleBar
            ? 'max-h-24 opacity-100 mb-4 translate-y-0 scale-100'
            : 'max-h-0 opacity-0 mb-0 -translate-y-4 scale-95 pointer-events-none'
            }`}
        >
          <BriefingPanel briefing={data?.briefing ?? ''} />
        </div>

        <div className="mx-auto flex w-full min-h-0 flex-1 flex-col gap-4 md:gap-6 xl:grid xl:grid-rows-[1fr_auto]">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 xl:flex xl:min-h-0 xl:w-full xl:flex-row xl:gap-6">
            {/* COLUMN 1: LEFT WING */}
            <div
              className={`flex min-w-0 flex-col gap-4 xl:min-h-0 ${wingTransition} ${isDormant ? leftWingDormantClasses : leftWingActiveClasses}`}
            >
              <TelemetryCard
                title="Weather"
                icon={CloudSun}
                primaryTemperatureF={primaryTemperatureF}
                weatherCondition={data?.weatherCondition}
                style={weatherCardStyle}
                className={`flex-none xl:flex-1 xl:min-h-0 ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
              >
                <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                  {weatherBody}
                </p>
              </TelemetryCard>

              <TelemetryCard
                title="Events"
                icon={Calendar}
                className={`flex-none xl:flex-1 xl:min-h-0 ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
              >
                <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">
                  {scheduleBody}
                </p>
              </TelemetryCard>

              <TelemetryCard
                title="Next F1 Race"
                icon={Flag}
                rawScheduleText={f1ScheduleTelemetryText}
                className="flex-none xl:flex-1 xl:min-h-0"
              />
            </div>

            {/* COLUMN 2: CENTER REACTOR */}
            <div
              className={`relative z-[var(--z-core-logo)] flex min-w-0 flex-col items-center gap-4 ${wingTransition} xl:gap-6 xl:min-h-0 ${isDormant ? centerColumnDormantClasses : centerColumnActiveClasses}`}
            >
              <div
                className={`w-full ${wingTransition} ${isDormant ? briefingDigestDormantClasses : briefingDigestActiveClasses} overflow-hidden flex flex-col`}
              >
                <BriefingDigest
                  insights={[
                    ...(data?.activeReminders ?? []).map((r) => `Reminder: ${r.note}`),
                    ...(data?.digest?.insights ?? []),
                  ]}
                  status={status}
                  isLoading={isTriggerLoading}
                  className="w-full h-full min-h-0"
                />
              </div>
              <div
                className={`flex h-64 flex-none flex-col items-center justify-center py-4 ${wingTransition} xl:h-full xl:min-h-0 xl:flex-1 xl:py-0 ${isDormant ? 'xl:flex-1 xl:justify-center' : ''}`}
              >
                <div className="relative flex flex-col items-center">
                  <div
                    className={`filter drop-shadow-[0_0_24px_rgba(var(--glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--glow-color),0.6)] ${isDormant ? 'scale-115 xl:scale-125' : 'scale-100'}`}
                  >
                    <ApexLogo
                      step={activeStep}
                      status={status}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      className="h-44 w-auto sm:h-52 xl:h-60"
                    />
                  </div>
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
                  {showAskApexBar ? (
                    <div
                      className="mt-3 flex w-full max-w-lg justify-center px-4 transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-auto opacity-100"
                    >
                      <AskApexBar
                        activeProfile={agentProfile}
                        onProfileChange={setAgentProfile}
                        onSubmit={handleAgentQuery}
                        profilesStatus={profilesStatus}
                        onSelectChip={handleAssistantChipSelect}
                        isSubmitting={isAssistantQuerying}
                        disabled={isSpeaking}
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT WING */}
            <div
              className={`flex min-w-0 flex-col gap-4 xl:min-h-0 ${wingTransition} ${isDormant ? rightWingDormantClasses : rightWingActiveClasses}`}
            >
              <TelemetryCard title="Inbox" icon={Mail} className="flex-none xl:flex-1 xl:min-h-0">
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
                      <ul className="min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                        {emailInfo.items.map((item, index) => (
                          <li
                            key={`${item.subject}-${item.time}-${index}`}
                            className="flex items-start justify-between gap-3"
                          >
                            <span className="break-words text-sm text-zinc-200">
                              {item.subject}
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

              <TelemetryCard title="News Wire" icon={Newspaper} className="flex-none xl:flex-1 xl:min-h-0">
                {isBusy(status) ? (
                  <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">
                    Loading news…
                  </p>
                ) : newsItems.length > 0 ? (
                  <ul className="min-h-0 overflow-y-auto pr-1 scrollbar-thin">
                    {newsItems.map((item, index) => (
                      <li
                        key={`${item.topic}-${index}`}
                        className={
                          index < newsItems.length - 1
                            ? 'border-b border-zinc-800/60 py-3 first:pt-0'
                            : 'py-3 first:pt-0'
                        }
                      >
                        <p className="text-xs font-semibold text-[color:var(--hud-accent)]">
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
                className={`flex-none xl:flex-1 xl:min-h-0 ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
                role="region"
                aria-label="Active reminders"
                data-slot="reminders-card"
              >
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  {activeReminders.length === 0 ? (
                    <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
                      No pending reminders.
                    </p>
                  ) : (
                    <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                      {activeReminders.map((reminder) => (
                        <ReminderListRow
                          key={reminder.id}
                          reminder={reminder}
                          onMarkRead={handleMarkReminderRead}
                        />
                      ))}
                    </ul>
                  )}
                  <div className="shrink-0">
                    <ReminderTerminal
                      refreshReminders={refreshReminders}
                      onReminderSaved={handleReminderSaved}
                    />
                  </div>
                </div>
              </TelemetryCard>
            </div>
          </div>
        </div>
      </div>

      <SystemDiagnostics
        diagnostics={diagnostics}
        diagnosticsStatus={diagnosticsStatus}
        isSpeaking={isSpeaking}
        isPipelinePolling={isPipelinePolling}
        status={status}
        confidenceScore={confidenceScore}
        pipelineStep={activeStep}
        failedConnectors={failedConnectors}
      />

      <AssistantDrawer
        isOpen={isAssistantOpen}
        onClose={() => {
          setAssistantOpen(false)
        }}
        onResetSession={resetAssistantSession}
        history={assistantHistory}
        isQuerying={isAssistantQuerying}
        latestTrace={assistantLatestTrace}
        activeProfile={agentProfile}
        profilesStatus={profilesStatus}
        onUnloadModel={unloadLocalModel}
        onSubmitFollowUp={handleAssistantFollowUp}
        error={assistantError}
      />
    </main>
  )
}
