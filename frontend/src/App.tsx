import { Activity, Calendar, CheckSquare, CloudSun, Flag } from 'lucide-react'
import { useMemo, type CSSProperties, type ReactElement } from 'react'

import { BriefingPanel } from './components/BriefingPanel'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderTerminal } from './components/ReminderTerminal'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { AtmosphericThemeProvider } from './context/AtmosphericThemeContext'
import { useApexData } from './hooks/useApexData'

function isBusy(status: 'idle' | 'loading' | 'success' | 'error'): boolean {
  return status === 'idle' || status === 'loading'
}

export default function App(): ReactElement {
  const apexData = useApexData()
  const {
    data,
    status,
    error,
    pipelineState,
    isPipelinePolling,
    activeReminders,
    refreshReminders,
    markReminderAsRead,
  } = apexData

  const activeStep = pipelineState?.step ?? null
  const isProcessing =
    status === 'loading' ||
    (activeStep !== null && activeStep >= 1 && activeStep <= 3)
  const isSpeaking = isPipelinePolling && activeStep === 4
  const showGlow = isProcessing || isSpeaking

  const waveGradient = isProcessing
    ? 'linear-gradient(to top, rgba(16, 185, 129, 0.22) 0%, rgba(16, 185, 129, 0.08) 40%, rgba(16, 185, 129, 0) 100%)'
    : 'linear-gradient(to top, rgba(234, 179, 8, 0.22) 0%, rgba(234, 179, 8, 0.08) 40%, rgba(234, 179, 8, 0) 100%)'

  const weatherCardStyle = useMemo((): CSSProperties | undefined => {
    const weatherText = data?.weather ?? ''

    if (weatherText.includes('Thunderstorm')) {
      return {
        '--hud-panel-bg': '#1a202c',
        '--hud-border-color': '#0e7490',
        '--hud-accent': '#06b6d4',
      } as CSSProperties
    }

    if (weatherText.includes('Clear')) {
      return {
        '--hud-panel-bg': '#020617',
        '--hud-border-color': '#854d0e',
        '--hud-accent': '#eab308',
      } as CSSProperties
    }

    return undefined
  }, [data?.weather])

  const hasSuccessfulData = status === 'success' && Boolean(data)
  const isTriggerLoading = status === 'loading'

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

  const f1ScheduleTelemetryText = data?.sports?.trim() ?? ''

  const headerTicker = (() => {
    if (status === 'error') {
      return { text: 'SYSTEM FAULT', className: 'text-red-500 animate-pulse' }
    }
    if (status === 'loading' && pipelineState !== null) {
      return {
        text: pipelineState.label,
        className: 'text-[color:var(--hud-accent)]',
      }
    }
    return { text: 'SYSTEM OPERATIONAL', className: 'text-emerald-500 opacity-80' }
  })()

  const centerMinHeight = 'min-h-56 md:min-h-72'

  return (
    <AtmosphericThemeProvider weatherReport={data?.weather}>
      <main className="relative min-h-dvh w-full overflow-hidden bg-[var(--hud-bg)] p-4 md:p-6">
        <div
          className={`pointer-events-none absolute inset-0 z-0 overflow-hidden transition-opacity duration-1000 ease-in-out ${showGlow ? 'opacity-100' : 'opacity-0'}`}
          aria-hidden
        >
          <div
            className={`h-[80dvh] w-full ${showGlow ? 'animate-rising-wave' : ''}`}
            style={{ background: waveGradient }}
          />
        </div>
        <header className="relative z-10 mb-6 flex w-full items-center justify-between border-b border-[color:var(--hud-border-color)] pb-4">
          <div className="flex items-baseline">
            <h1
              className={`m-0 text-3xl font-extrabold tracking-widest md:text-4xl ${
                isPipelinePolling
                  ? 'animate-shimmer'
                  : 'text-[color:var(--hud-accent)]'
              }`}
            >
              APEX
            </h1>
            <span className="mb-1 ml-3 hidden self-end text-xs uppercase tracking-widest text-[color:var(--hud-text)] opacity-40 sm:block">
              AUTOMATED PERSONAL ENVIRONMENT XYLEM
            </span>
          </div>
          <p
            className={`m-0 font-mono text-sm uppercase tracking-wider ${headerTicker.className}`}
            aria-live="polite"
            data-slot="header-status-ticker"
          >
            {headerTicker.text}
          </p>
        </header>
        <div className="relative z-10 mx-auto grid w-full grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
          <TelemetryCard
            title="Weather"
            icon={CloudSun}
            primaryTemperatureF={primaryTemperatureF}
            style={weatherCardStyle}
            className={`min-h-40 ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
          >
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
              {weatherBody}
            </p>
          </TelemetryCard>

          <div className={`min-w-0 ${centerMinHeight}`}>
            <BriefingPanel
              briefing={data?.briefing ?? ''}
              status={status}
              error={error}
              isLoading={isTriggerLoading}
              isSpeaking={isSpeaking}
            />
          </div>

          <TelemetryCard
            title="Schedule"
            icon={Calendar}
            className={`min-h-40 ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
          >
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
              {scheduleBody}
            </p>
          </TelemetryCard>

          <TelemetryCard
            title="F1 Schedule"
            icon={Flag}
            rawScheduleText={f1ScheduleTelemetryText}
            className="min-h-40"
          />

          <TelemetryCard
            title="Reminders"
            icon={CheckSquare}
            className={`min-h-40 ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
            role="region"
            aria-label="Active reminders"
            data-slot="reminders-card"
          >
            {activeReminders.length === 0 ? (
              <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
                No pending reminders.
              </p>
            ) : (
              <ul className="space-y-2">
                {activeReminders.map((reminder) => (
                  <ReminderListRow
                    key={reminder.id}
                    reminder={reminder}
                    onMarkRead={handleMarkReminderRead}
                  />
                ))}
              </ul>
            )}
            <ReminderTerminal refreshReminders={refreshReminders} />
          </TelemetryCard>

          <TelemetryCard
            title="System Diagnostics"
            icon={Activity}
            className="border-2 border-[color:var(--hud-accent)] md:col-span-2 xl:col-span-2"
            role="region"
            aria-label="System diagnostics"
            data-slot="system-diagnostics-card"
          >
            <SystemDiagnostics />
          </TelemetryCard>
        </div>
      </main>
    </AtmosphericThemeProvider>
  )
}
