import { describe, expect, it } from 'vitest'

import type { TelemetryModuleEntry } from '../types/telemetry'
import { resolveEmailTelemetry } from './emailTelemetry'

function emailModule(data: Record<string, unknown>, overrides: Partial<TelemetryModuleEntry> = {}): TelemetryModuleEntry {
  return {
    name: 'email', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: null,
    display_text: 'Email Telemetry: prose is not a data contract.', data, ...overrides,
  }
}

describe('resolveEmailTelemetry', () => {
  it('preserves punctuation and Unicode from typed preview fields', () => {
    expect(resolveEmailTelemetry(emailModule({
      count: 2,
      emails: [
        { subject: "Owner's [alert] | 東京 🌦️", time: '  9:15 AM | now  ' },
        { subject: '', time: '' },
      ],
    }))).toEqual({
      state: 'available',
      count: 2,
      items: [
        { subject: "Owner's [alert] | 東京 🌦️", time: '  9:15 AM | now  ' },
        { subject: '(No subject)', time: '' },
      ],
    })
  })

  it('treats a valid empty payload and zero count as available', () => {
    expect(resolveEmailTelemetry(emailModule({ count: 0, emails: [] }))).toEqual({ state: 'available', count: 0, items: [] })
  })

  it('filters malformed rows while retaining valid rows', () => {
    expect(resolveEmailTelemetry(emailModule({
      count: 3,
      emails: [null, { subject: 'kept', time: '' }, { subject: 'bad time', time: 1 }, { subject: '', time: 'now' }],
    }))).toEqual({
      state: 'available', count: 3,
      items: [{ subject: 'kept', time: '' }, { subject: '(No subject)', time: 'now' }],
    })
  })

  it.each([
    { count: -1, emails: [] },
    { count: 1.5, emails: [] },
    { count: '1', emails: [] },
    { count: 1 },
    { count: 1, emails: 'subject' },
    { count: 1, emails: [{ subject: 'bad', time: 1 }] },
  ])('marks invalid payload %# unavailable', (data) => {
    expect(resolveEmailTelemetry(emailModule(data as Record<string, unknown>))).toMatchObject({ state: 'unavailable', count: null, items: [] })
  })

  it('keeps valid stale payload content after an unavailable refresh', () => {
    expect(resolveEmailTelemetry(emailModule({ count: 1, emails: [{ subject: 'retained', time: '' }] }, {
      status: 'unavailable', freshness: 'stale', reason_code: 'provider_error',
    }))).toEqual({ state: 'available', count: 1, items: [{ subject: 'retained', time: '' }] })
    expect(resolveEmailTelemetry(emailModule({ count: 0, emails: [] }, { status: 'unavailable', freshness: 'none' }))).toMatchObject({ state: 'unavailable' })
    expect(resolveEmailTelemetry(emailModule({ count: 1, emails: [{ subject: 'degraded', time: '' }] }, {
      status: 'degraded', freshness: 'fresh_cache', reason_code: 'partial_data',
    }))).toMatchObject({ state: 'available', count: 1, items: [{ subject: 'degraded', time: '' }] })
  })

  it('distinguishes disabled and missing modules', () => {
    expect(resolveEmailTelemetry(emailModule({ count: 0, emails: [] }, { status: 'disabled' }))).toMatchObject({ state: 'disabled' })
    expect(resolveEmailTelemetry(undefined)).toMatchObject({ state: 'unavailable', count: null })
  })
})
