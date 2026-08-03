import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { FootballTelemetry } from '../lib/footballTelemetry'
import type { TelemetryModuleEntry } from '../types/telemetry'
import { FootballFixtureList } from './FootballFixtureList'

const module: TelemetryModuleEntry = { name: 'football', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: null, display_text: '', data: {} }
const telemetry: FootballTelemetry = { configuredTeamCount: 1, fixtures: [{ fixtureId: '1', team: 'Barcelona', opponent: 'Real Madrid', homeOrAway: 'away', competition: 'La Liga', kickoff: 'Friday at 14:00' }] }

describe('FootballFixtureList', () => {
  it('renders venue, competition, and kickoff from structured telemetry', () => {
    render(<FootballFixtureList hasSnapshot module={module} telemetry={telemetry} />)
    expect(screen.getByText(/Barcelona · Away vs Real Madrid/)).toBeInTheDocument()
    expect(screen.getByText('La Liga')).toBeInTheDocument()
    expect(screen.getByText('Friday at 14:00')).toBeInTheDocument()
  })

  it('renders the enabled empty state', () => {
    render(<FootballFixtureList hasSnapshot module={module} telemetry={{ configuredTeamCount: 1, fixtures: [] }} />)
    expect(screen.getByText('No upcoming football fixtures.')).toBeInTheDocument()
  })
})
