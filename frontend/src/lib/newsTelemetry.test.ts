import { describe, expect, it } from 'vitest'

import type { TelemetryModuleEntry } from '../types/telemetry'
import { resolveNewsTelemetry } from './newsTelemetry'

function newsModule(data: Record<string, unknown>, overrides: Partial<TelemetryModuleEntry> = {}): TelemetryModuleEntry {
  return {
    name: 'news', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: null,
    display_text: '[NEWS TELEMETRY] prose remains summary only.', data, ...overrides,
  }
}

describe('resolveNewsTelemetry', () => {
  it('preserves headline punctuation, brackets, pipes, and Unicode', () => {
    expect(resolveNewsTelemetry(newsModule({ headlines: [
      { topic: '科技 [AI] | 世界', headline: "Owner's report: [new] | 東京 🌱" },
    ] }))).toEqual({ state: 'available', items: [
      { topic: '科技 [AI] | 世界', headline: "Owner's report: [new] | 東京 🌱" },
    ] })
  })

  it('treats an empty headlines array as an available empty result', () => {
    expect(resolveNewsTelemetry(newsModule({ headlines: [] }))).toEqual({ state: 'available', items: [] })
  })

  it('filters malformed rows and rejects a nonempty array with no valid rows', () => {
    expect(resolveNewsTelemetry(newsModule({ headlines: [
      { topic: 'Local', headline: 'Keep this one' }, null,
      { topic: ' ', headline: 'blank topic' }, { topic: 'World', headline: 3 },
    ] }))).toEqual({ state: 'available', items: [{ topic: 'Local', headline: 'Keep this one' }] })
    expect(resolveNewsTelemetry(newsModule({ headlines: [null, { topic: '', headline: 'bad' }] }))).toMatchObject({ state: 'unavailable', items: [] })
  })

  it.each([undefined, null, 'headline', { count: 1 }])('marks missing or wrong envelopes unavailable', (headlines) => {
    expect(resolveNewsTelemetry(newsModule({ headlines }))).toMatchObject({ state: 'unavailable', items: [] })
  })

  it('retains valid stale content, rejects fresh unavailable content, and marks disabled', () => {
    expect(resolveNewsTelemetry(newsModule({ headlines: [{ topic: 'Weather', headline: 'Rain later' }] }, {
      status: 'unavailable', freshness: 'stale', reason_code: 'provider_error',
    }))).toMatchObject({ state: 'available', items: [{ topic: 'Weather', headline: 'Rain later' }] })
    expect(resolveNewsTelemetry(newsModule({ headlines: [] }, { status: 'unavailable', freshness: 'none' }))).toMatchObject({ state: 'unavailable' })
    expect(resolveNewsTelemetry(newsModule({ headlines: [] }, { status: 'disabled' }))).toMatchObject({ state: 'disabled' })
    expect(resolveNewsTelemetry(newsModule({ headlines: [{ topic: 'Local', headline: 'Degraded item' }] }, {
      status: 'degraded', freshness: 'fresh_cache', reason_code: 'partial_data',
    }))).toMatchObject({ state: 'available', items: [{ topic: 'Local', headline: 'Degraded item' }] })
  })
})
