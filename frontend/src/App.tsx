import { Calendar, CloudSun, Terminal } from 'lucide-react'
import type { ReactElement } from 'react'

import { BriefingPanel } from './components/BriefingPanel'
import { DiagnosticProgress } from './components/DiagnosticProgress'
import { TelemetryCard } from './components/TelemetryCard'
import { useApexData } from './hooks/useApexData'

function isBusy(status: 'idle' | 'loading' | 'success' | 'error'): boolean {
  return status === 'idle' || status === 'loading'
}

export default function App(): ReactElement {
  const { data, status, error } = useApexData()
  const hasSuccessfulData = status === 'success' && Boolean(data)

  const weatherBody = (() => {
    if (hasSuccessfulData) {
      const weather = data?.weather?.trim() ?? ''
      return weather.length > 0 ? weather : 'No weather data.'
    }
    if (isBusy(status)) {
      return 'Loading weather…'
    }
    return error ?? 'Weather unavailable.'
  })()

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
        <TelemetryCard title="Weather" icon={CloudSun} className="min-h-40">
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
                <DiagnosticProgress isLoading={status === 'loading'} />
              </div>
            </TelemetryCard>
          )}
        </div>

        <TelemetryCard
          title="Schedule"
          icon={Calendar}
          className="min-h-40 opacity-95"
        >
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
            {scheduleBody}
          </p>
        </TelemetryCard>
      </div>
    </main>
  )
}
