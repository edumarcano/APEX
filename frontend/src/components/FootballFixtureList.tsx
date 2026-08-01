import type { ReactElement } from 'react'

import type { FootballTelemetry } from '../lib/footballTelemetry'
import type { TelemetryModuleEntry } from '../types/telemetry'

interface FootballFixtureListProps {
  telemetry: FootballTelemetry
  module: TelemetryModuleEntry | undefined
  hasSnapshot: boolean
}

export function FootballFixtureList({ telemetry, module, hasSnapshot }: FootballFixtureListProps): ReactElement | null {
  if (!module || module.status === 'disabled') return null
  if (module.status === 'unavailable') return null
  if (telemetry.fixtures.length === 0) {
    return (
      <p className="mt-3 text-sm text-[color:var(--hud-muted-text)]">
        {hasSnapshot ? 'No upcoming football fixtures.' : 'Football unavailable.'}
      </p>
    )
  }
  return (
    <section className="mt-3 border-t border-white/[0.08] pt-3" aria-label="Football fixtures">
      <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
        Football
      </p>
      <ul className="space-y-2">
        {telemetry.fixtures.slice(0, 3).map((fixture, index) => (
          <li key={fixture.fixtureId} className="flex items-start justify-between gap-3">
            <span className="flex min-w-0 items-start gap-2">
              <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
              <span className="min-w-0 break-words text-sm text-zinc-200">
                <span className="block">{fixture.team} · {fixture.homeOrAway === 'home' ? 'Home' : 'Away'} vs {fixture.opponent}</span>
                <span className="block text-xs text-[color:var(--hud-muted-text)]">{fixture.competition}</span>
              </span>
            </span>
            <span className="shrink-0 font-mono text-xs text-zinc-500">{fixture.kickoff}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
