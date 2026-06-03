import { Activity, Calendar, CheckSquare, CloudSun, Flag } from 'lucide-react'
import { useMemo, useState, type CSSProperties, type ReactElement } from 'react'

import { ApexLogo } from './components/ApexLogo'
import { BriefingPanel } from './components/BriefingPanel'
import { ReminderListRow } from './components/ReminderListRow'
import { ReminderTerminal } from './components/ReminderTerminal'
import { SystemDiagnostics } from './components/SystemDiagnostics'
import { TelemetryCard } from './components/TelemetryCard'
import { VocalOrb } from './components/VocalOrb'
import { AtmosphericThemeProvider } from './context/AtmosphericThemeContext'
import { useApexData } from './hooks/useApexData'
import type { WeatherConditionArchetype } from './types/telemetry'

function isBusy(status: 'idle' | 'loading' | 'success' | 'error'): boolean {
  return status === 'idle' || status === 'loading'
}

export default function App(): ReactElement {
  const [reminderPulseCount, setReminderPulseCount] = useState(0)
  const apexData = useApexData()
  const {
    data,
    status,
    error,
    pipelineState,
    isPipelinePolling,
    isSpeaking,
    activeReminders,
    refreshReminders,
    markReminderAsRead,
  } = apexData

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

  const headerTicker = (() => {
    if (status === 'error') {
      return { text: 'SYSTEM FAULT', className: 'text-[#DC2626] animate-pulse' }
    }
    if (status === 'loading' && pipelineState !== null) {
      return {
        text: pipelineState.label,
        className: 'text-[color:var(--hud-accent)]',
      }
    }
    return { text: 'SYSTEM OPERATIONAL', className: 'text-[#39FF88] opacity-80' }
  })()

  return (
    <AtmosphericThemeProvider weatherReport={data?.weather}>
      <main
        className="relative min-h-dvh w-full overflow-hidden bg-[var(--hud-bg)] p-4 md:p-6"
        style={{ '--glow-color': glowColor } as CSSProperties}
      >
<div 
  className="pointer-events-none absolute inset-0 z-0 overflow-hidden transition-opacity duration-1000 ease-in-out"
  style={{
    opacity: showGlow ? 1 : 0,
    '--glow-color': glowColor,
  } as React.CSSProperties}
>
  {showGlow && (
    <>
      {/* Nebula 1: Top-Right */}
      <div 
        className="hud-nebula-blob animate-nebula-1 top-[-35%] right-[-35%] w-[110%] h-[110%]"
        style={{ background: 'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.12) 45%, rgba(var(--glow-color), 0.04) 75%, rgba(0,0,0,0) 100%)' }}
      />
      {/* Nebula 2: Bottom-Left */}
      <div 
        className="hud-nebula-blob animate-nebula-2 bottom-[-35%] left-[-35%] w-[110%] h-[110%]"
        style={{ background: 'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.12) 45%, rgba(var(--glow-color), 0.04) 75%, rgba(0,0,0,0) 100%)' }}
      />
      {/* Nebula 3: Center-Slicing Diagonal */}
      <div 
        className="hud-nebula-blob animate-nebula-3 top-[10%] left-[10%] w-[100%] h-[100%]"
        style={{ background: 'radial-gradient(circle, rgba(var(--glow-color), 0.35) 0%, rgba(var(--glow-color), 0.08) 45%, rgba(var(--glow-color), 0.02) 75%, rgba(0,0,0,0) 100%)' }}
      />
    </>
  )}
</div>
        <header className="relative z-10 mb-6 grid w-full grid-cols-3 items-center border-b border-[color:var(--hud-border-color)] pb-4">
          <div className="flex items-baseline justify-self-start">
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
          <div className="flex justify-center justify-self-center">
            <VocalOrb isSpeaking={isSpeaking} className="h-12 w-auto" />
          </div>
          <p
            className={`m-0 justify-self-end font-mono text-sm uppercase tracking-wider ${headerTicker.className}`}
            aria-live="polite"
            data-slot="header-status-ticker"
          >
            {headerTicker.text}
          </p>
        </header>
        <div className="relative z-10 mx-auto grid w-full grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
          {/* COLUMN 1: LEFT WING */}
          <div className="flex flex-col gap-4 md:gap-6">
            <TelemetryCard
              title="Weather"
              icon={CloudSun}
              primaryTemperatureF={primaryTemperatureF}
              weatherCondition={data?.weatherCondition}
              style={weatherCardStyle}
              className={`min-h-40 ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
            >
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
                {weatherBody}
              </p>
            </TelemetryCard>

            <TelemetryCard
              title="Events"
              icon={Calendar}
              className={`min-h-40 ${staggerTransition} ${scheduleDimmed ? 'opacity-25' : 'opacity-100'}`}
            >
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
                {scheduleBody}
              </p>
            </TelemetryCard>

            <TelemetryCard
              title="Next F1 Race"
              icon={Flag}
              rawScheduleText={f1ScheduleTelemetryText}
              className="min-h-40"
            />
          </div>

          {/* COLUMN 2: CENTER REACTOR */}
          <div className="flex flex-col items-center justify-center h-full py-6 min-h-[30rem] xl:col-span-1">
            <div className="flex h-full w-full items-center justify-center">
              <ApexLogo
                step={activeStep}
                status={status}
                isSpeaking={isSpeaking}
                reminderPulseCount={reminderPulseCount}
                className="h-64 xl:h-72 w-auto filter drop-shadow-[0_0_24px_rgba(var(--glow-color),0.45)]"
              />
            </div>
          </div>

          {/* COLUMN 3: RIGHT WING */}
          <div className="flex flex-col gap-4 md:gap-6">
            <div className="flex min-h-40 w-full items-center justify-center">
              <BriefingPanel
                briefing={data?.briefing ?? ''}
                status={status}
                error={error}
                isLoading={isTriggerLoading}
                isSpeaking={isSpeaking && activeStep === 4}
              />
            </div>

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
              <ReminderTerminal
                refreshReminders={refreshReminders}
                onReminderSaved={handleReminderSaved}
              />
            </TelemetryCard>
          </div>

          {/* FULL DECK FOOTER */}
          <TelemetryCard
            title="System Diagnostics"
            icon={Activity}
            className="border-2 border-[color:var(--hud-accent)] md:col-span-2 xl:order-7 xl:col-span-3"
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
