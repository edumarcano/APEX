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
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react'

import { ApexLogo } from './components/ApexLogo'
import { CelestialBackground } from './components/CelestialBackground'
import { BriefingDigest } from './components/BriefingDigest'
import { BriefingPanel } from './components/BriefingPanel'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderTerminal } from './components/ReminderTerminal'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VocalOrb } from './components/VocalOrb'
import { useApexData } from './hooks/useApexData'
import { useSystemDiagnostics } from './hooks/useSystemDiagnostics'
import type { WeatherConditionArchetype } from './types/telemetry'

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

export default function App(): ReactElement {
  const [reminderPulseCount, setReminderPulseCount] = useState(0)
  const [lastBriefingTime, setLastBriefingTime] = useState<string | null>(null)
  const [prevStatus, setPrevStatus] = useState<string>('idle')

  const { diagnostics, status: diagnosticsStatus } = useSystemDiagnostics()
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
    refreshReminders,
    markReminderAsRead,
    triggerSynthesis,
  } = apexData

  const resolvedTtsEngine = pipelineState?.active_tts_engine ?? active_tts_engine
  const resolvedSystemThrottled =
    pipelineState?.system_load_throttled ?? system_load_throttled

  const activeStep = pipelineState?.step ?? null
  const isProcessing =
    status === 'loading' ||
    (activeStep !== null && activeStep >= 1 && activeStep <= 3)
  const showGlow = isProcessing || isSpeaking || status === 'success'

  const glowColor = isProcessing
    ? '57, 255, 136' // Processing Green for Stages 1–3
    : isSpeaking || status === 'success'
      ? '251, 191, 36' // Ready Gold for Stage 4 and delivered state
      : '0, 0, 0'

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
  const showTriggerButton = status === 'idle'
  const isTriggerDisabled = isProcessing
  const pendingReminderCount = activeReminders.length
  const showStandbyNotification =
    status === 'idle' && pendingReminderCount > 0

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

      void triggerSynthesis()
    }

    window.addEventListener('keydown', handleGlobalEnter)
    return () => {
      window.removeEventListener('keydown', handleGlobalEnter)
    }
  }, [status, triggerSynthesis])

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
          className="absolute inset-0 z-[var(--z-reactive-glow)] pointer-events-none overflow-hidden transition-opacity duration-1000 ease-in-out"
          style={{
            opacity: showGlow ? 1 : 0,
            '--glow-color': glowColor,
          } as CSSProperties}
        >
          {showGlow && (
            <>
              {/* Nebula 1: Top-Right */}
              <div
                className="hud-nebula-blob animate-nebula-1 top-[-35%] right-[-35%] h-[110%] w-[110%] will-change-transform will-change-[opacity]"
                style={{
                  background:
                    'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.12) 45%, rgba(var(--glow-color), 0.04) 75%, rgba(0,0,0,0) 100%)',
                }}
              />
              {/* Nebula 2: Bottom-Left */}
              <div
                className="hud-nebula-blob animate-nebula-2 bottom-[-35%] left-[-35%] h-[110%] w-[110%] will-change-transform will-change-[opacity]"
                style={{
                  background:
                    'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.12) 45%, rgba(var(--glow-color), 0.04) 75%, rgba(0,0,0,0) 100%)',
                }}
              />
              {/* Nebula 3: Center-Slicing Diagonal */}
              <div
                className="hud-nebula-blob animate-nebula-3 top-[10%] left-[10%] h-[100%] w-[100%] will-change-transform will-change-[opacity]"
                style={{
                  background:
                    'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.08) 45%, rgba(var(--glow-color), 0.02) 75%, rgba(0,0,0,0) 100%)',
                }}
              />
            </>
          )}
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
              {showTriggerButton && (
                <button
                  type="button"
                  onClick={() => {
                    void triggerSynthesis()
                  }}
                  disabled={isTriggerDisabled}
                  className="inline-flex rounded-lg border border-[#0F4DB8]/40 bg-[#0F4DB8]/10 px-2.5 py-1 font-mono text-[9px] uppercase tracking-widest text-[#FBBF24] transition-all hover:border-[#0F4DB8]/60 hover:bg-[#0F4DB8]/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40 sm:px-3 sm:text-[10px]"
                  aria-label="Initiate system briefing"
                  data-slot="synthesis-trigger"
                >
                  INITIATE SYSTEM BRIEFING
                </button>
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
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-3 xl:min-h-0">
              {/* COLUMN 1: LEFT WING */}
              <div className="flex flex-col gap-4 xl:min-h-0">
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
              <div className="relative z-[var(--z-core-logo)] flex flex-col items-center gap-4 xl:col-span-1 xl:gap-6 xl:min-h-0">
                <BriefingDigest
                  insights={[
                    ...(data?.activeReminders ?? []).map((r) => `Reminder: ${r.note}`),
                    ...(data?.digest?.insights ?? []),
                  ]}
                  status={status}
                  isLoading={isTriggerLoading}
                  className="flex-none w-full xl:flex-1 xl:min-h-0"
                />
                <div className="flex h-64 flex-none flex-col items-center justify-center py-4 xl:h-full xl:min-h-0 xl:flex-1 xl:py-0">
                  <div className="filter drop-shadow-[0_0_24px_rgba(var(--glow-color),0.45)] transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:scale-[1.03] hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--glow-color),0.6)]">
                    <ApexLogo
                      step={activeStep}
                      status={status}
                      isSpeaking={isSpeaking}
                      reminderPulseCount={reminderPulseCount}
                      className="h-44 w-auto sm:h-52 xl:h-60"
                    />
                  </div>
                  {showStandbyNotification && (
                    <p
                      className="mt-3 font-mono text-[11px] uppercase tracking-widest text-amber-400/70"
                      aria-live="polite"
                      data-slot="standby-notification"
                    >
                      [{pendingReminderCount}{' '}
                      {pendingReminderCount === 1 ? 'Reminder' : 'Reminders'} Pending]
                    </p>
                  )}
                </div>
              </div>

              {/* COLUMN 3: RIGHT WING */}
              <div className="flex flex-col gap-4 xl:min-h-0">
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
    </main>
  )
}
