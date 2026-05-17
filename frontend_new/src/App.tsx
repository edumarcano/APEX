import { Calendar, CloudSun, Terminal } from 'lucide-react'
import type { ReactElement } from 'react'

import { TelemetryCard } from './components/TelemetryCard'

export default function App(): ReactElement {
  return (
    <main className="min-h-dvh w-full bg-[var(--hud-bg)] p-4 md:p-6">
      <div className="mx-auto grid w-full grid-cols-1 gap-4 md:grid-cols-3 md:gap-6">
        <TelemetryCard title="System Status" icon={CloudSun} className="min-h-40" />

        <TelemetryCard
          title="Core Briefing"
          icon={Terminal}
          className="min-h-56 md:min-h-72"
          role="region"
          aria-label="Briefing panel"
          data-slot="briefing-panel"
        />

        <TelemetryCard
          title="Schedule & Tasks"
          icon={Calendar}
          className="min-h-40 opacity-95"
        />
      </div>
    </main>
  )
}
