import { Calendar, CloudSun, Terminal } from 'lucide-react'
import { useState, type ReactElement } from 'react'

import { BriefingPanel } from './components/BriefingPanel'
import { DiagnosticProgress } from './components/DiagnosticProgress'
import { TelemetryCard } from './components/TelemetryCard'
import { useApexData } from './hooks/useApexData'

function isBusy(status: 'idle' | 'loading' | 'success' | 'error'): boolean {
  return status === 'idle' || status === 'loading'
}

export default function App(): ReactElement {
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const { data, status, error } = useApexData()
  const hasSuccessfulData = status === 'success' && Boolean(data)

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
      const reminders = data?.reminders?.trim() ?? ''
      const blocks = [calendar, reminders].filter((block) => block.length > 0)
      return blocks.length > 0 ? blocks.join('\n\n') : 'No schedule entries.'
    }
    if (isBusy(status)) {
      return 'Loading schedule…'
    }
    return error ?? 'Schedule unavailable.'
  })()

  const centerMinHeight = 'min-h-56 md:min-h-72'

  return (
    <main className="min-h-dvh w-full bg-[var(--hud-bg)] p-4 md:p-6">
      <div className="mx-auto grid w-full grid-cols-1 gap-4 md:grid-cols-3 md:gap-6">
        <TelemetryCard
          title="Weather"
          icon={CloudSun}
          primaryTemperatureF={primaryTemperatureF}
          className={`min-h-40 ${staggerTransition} ${weatherDimmed ? 'opacity-25' : 'opacity-100'}`}
        >
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
            {weatherBody}
          </p>
        </TelemetryCard>

        <div className={`min-w-0 ${centerMinHeight}`}>
          {hasSuccessfulData ? (
            <BriefingPanel briefing={data?.briefing ?? ''} />
          ) : (
            <TelemetryCard
              title="Core Briefing"
              icon={Terminal}
              className="h-full min-h-56 md:min-h-72"
              role="region"
              aria-label="Briefing panel"
              data-slot="briefing-panel"
            >
              <div className="flex flex-col gap-6 h-full justify-between">
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
                  {isBusy(status)
                    ? 'Fetching briefing stream…'
                    : (error ?? 'Briefing unavailable.')}
                </p>
                <DiagnosticProgress
                  isLoading={status === 'loading'}
                  onStepChange={setActiveStep}
                />
              </div>
            </TelemetryCard>
          )}
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
      </div>
    </main>
  )
}
