import type { TelemetryModuleEntry } from '../types/telemetry'

export type TelemetryContentState = 'available' | 'unavailable' | 'disabled'

export interface ResolvedEmailTelemetry {
  state: TelemetryContentState
  count: number | null
  items: Array<{ subject: string; time: string }>
}

const EMPTY_EMAIL: ResolvedEmailTelemetry = {
  state: 'unavailable',
  count: null,
  items: [],
}

/** Resolve display-safe email fields from the typed snapshot payload. */
export function resolveEmailTelemetry(
  module: TelemetryModuleEntry | null | undefined,
): ResolvedEmailTelemetry {
  if (!module) return EMPTY_EMAIL
  if (module.status === 'disabled') return { ...EMPTY_EMAIL, state: 'disabled' }

  const rawCount = module.data.count
  const rawEmails = module.data.emails
  if (!Number.isInteger(rawCount) || typeof rawCount !== 'number' || rawCount < 0 || !Array.isArray(rawEmails)) {
    return EMPTY_EMAIL
  }

  const items = rawEmails.flatMap((row) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) return []
    const { subject, time } = row as Record<string, unknown>
    if (typeof subject !== 'string' || typeof time !== 'string') return []
    return [{ subject: subject.trim() ? subject : '(No subject)', time }]
  })
  if (rawEmails.length > 0 && items.length === 0) return EMPTY_EMAIL

  if (module.status === 'unavailable' && module.freshness !== 'stale') return EMPTY_EMAIL

  return { state: 'available', count: rawCount, items }
}
