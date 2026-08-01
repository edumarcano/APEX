import type { TelemetryModuleEntry } from '../types/telemetry'

export interface FootballFixtureDisplay {
  fixtureId: string
  team: string
  opponent: string
  homeOrAway: 'home' | 'away'
  competition: string
  kickoff: string
}

export interface FootballTelemetry {
  fixtures: FootballFixtureDisplay[]
  configuredTeamCount: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

function formatKickoff(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const day = date.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${day} at ${time}`
}

function parseFixture(value: unknown): FootballFixtureDisplay | null {
  if (!isRecord(value)) return null
  const fixtureId = typeof value.fixture_id === 'string' ? value.fixture_id.trim() : ''
  const team = typeof value.team === 'string' ? value.team.trim() : ''
  const opponent = typeof value.opponent === 'string' ? value.opponent.trim() : ''
  const competition = typeof value.competition === 'string' ? value.competition.trim() : ''
  const kickoffAt = typeof value.kickoff_at === 'string' ? value.kickoff_at.trim() : ''
  const homeOrAway = value.home_or_away
  if (!fixtureId || !team || !opponent || !competition || !kickoffAt || (homeOrAway !== 'home' && homeOrAway !== 'away')) {
    return null
  }
  return { fixtureId, team, opponent, homeOrAway, competition, kickoff: formatKickoff(kickoffAt) }
}

/** Read the structured football connector contract; football has no text fallback. */
export function resolveFootballTelemetry(module: TelemetryModuleEntry | undefined): FootballTelemetry {
  const data = module?.data
  if (!isRecord(data) || !Array.isArray(data.fixtures)) {
    return { fixtures: [], configuredTeamCount: 0 }
  }
  return {
    fixtures: data.fixtures.map(parseFixture).filter((fixture): fixture is FootballFixtureDisplay => fixture !== null),
    configuredTeamCount: nonNegativeInteger(data.configured_team_count) ?? 0,
  }
}
