import type { TelemetryModuleEntry } from '../types/telemetry'
import type { TelemetryContentState } from './emailTelemetry'

export interface ResolvedNewsTelemetry {
  state: TelemetryContentState
  items: Array<{ topic: string; headline: string }>
}

const EMPTY_NEWS: ResolvedNewsTelemetry = { state: 'unavailable', items: [] }

/** Resolve display-safe headline fields from the typed snapshot payload. */
export function resolveNewsTelemetry(
  module: TelemetryModuleEntry | null | undefined,
): ResolvedNewsTelemetry {
  if (!module) return EMPTY_NEWS
  if (module.status === 'disabled') return { ...EMPTY_NEWS, state: 'disabled' }

  const rawHeadlines = module.data.headlines
  if (!Array.isArray(rawHeadlines)) return EMPTY_NEWS

  const items = rawHeadlines.flatMap((row) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) return []
    const { topic, headline } = row as Record<string, unknown>
    if (
      typeof topic !== 'string' || !topic.trim() ||
      typeof headline !== 'string' || !headline.trim()
    ) return []
    return [{ topic, headline }]
  })
  if (rawHeadlines.length > 0 && items.length === 0) return EMPTY_NEWS
  if (module.status === 'unavailable' && module.freshness !== 'stale') return EMPTY_NEWS

  return { state: 'available', items }
}
