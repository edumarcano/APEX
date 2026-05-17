import type { ReactElement } from 'react'

export default function App(): ReactElement {
  return (
    <main className="min-h-dvh w-full bg-[var(--hud-bg)] p-4 md:p-6">
      <div className="mx-auto grid w-full grid-cols-1 gap-4 md:grid-cols-3 md:gap-6">
        <div className="min-h-40 rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)]" />

        <div
          className="min-h-56 rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)] md:min-h-72"
          role="region"
          aria-label="Briefing panel"
          data-slot="briefing-panel"
        />

        <div className="min-h-40 rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)] opacity-95" />
      </div>
    </main>
  )
}
