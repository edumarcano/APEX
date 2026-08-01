import { describe, expect, it } from 'vitest'

import type { TelemetryModuleEntry } from '../types/telemetry'
import { resolveFootballTelemetry } from './footballTelemetry'

const module: TelemetryModuleEntry = {
  name: 'football', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: '2026-07-24T12:00:00Z', display_text: 'ignored',
  data: { configured_team_count: 2, fixtures: [
    { fixture_id: '1', team_id: 81, team: 'Barcelona', opponent: 'Real Madrid', home_or_away: 'home', competition_id: 2014, competition: 'La Liga', kickoff_at: '2026-07-25T18:00:00Z' },
    { fixture_id: 'bad', team: 'Discarded', home_or_away: 'home' },
  ] },
}

describe('resolveFootballTelemetry', () => {
  it('uses structured fixtures and formats the kickoff in the browser locale', () => {
    const result = resolveFootballTelemetry(module)
    expect(result.configuredTeamCount).toBe(2)
    expect(result.fixtures).toHaveLength(1)
    expect(result.fixtures[0]).toMatchObject({ team: 'Barcelona', opponent: 'Real Madrid', homeOrAway: 'home', competition: 'La Liga' })
    expect(result.fixtures[0].kickoff).toMatch(/at \d{2}:\d{2}$/)
  })
})
