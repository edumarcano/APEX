import type { TelemetryLedState } from '../components/TelemetryCard'
import type {
  ConnectorFreshness,
  ConnectorHealthStatus,
  TelemetryModuleEntry,
} from '../types/telemetry'

/** Map a typed module entry (+ optional in-flight refresh) to a card LED. */
export function resolveModuleLedState(
  module: TelemetryModuleEntry | null | undefined,
  isRefreshing: boolean,
): TelemetryLedState {
  if (isRefreshing) return 'loading'
  if (!module) return 'none'
  if (module.status === 'disabled') return 'none'
  if (module.status === 'unavailable') return 'error'
  if (module.freshness === 'stale') return 'stale'
  if (module.freshness === 'live' || module.freshness === 'fresh_cache') return 'live'
  if (module.status === 'healthy' || module.status === 'degraded') return 'live'
  return 'none'
}

export function moduleReasonLabel(module: TelemetryModuleEntry | null | undefined): string | null {
  if (!module) return null
  if (module.status === 'disabled') return 'Disabled'
  if (module.reason_code && module.reason_code !== 'ok') {
    return module.reason_code.replaceAll('_', ' ')
  }
  return null
}

export function hasModuleContent(module: TelemetryModuleEntry | null | undefined): boolean {
  return Boolean(module?.display_text?.trim())
}

export type ModuleVisualStatus = ConnectorHealthStatus | 'loading'

export function describeModuleState(
  status: ConnectorHealthStatus | undefined,
  freshness: ConnectorFreshness | undefined,
  isRefreshing: boolean,
): string {
  if (isRefreshing) return 'Refreshing…'
  if (!status) return 'Waiting for telemetry…'
  if (status === 'disabled') return 'Connector disabled.'
  if (status === 'unavailable') return 'Unavailable.'
  if (freshness === 'stale') return 'Stale data retained.'
  return ''
}
