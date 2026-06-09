import type { ReactElement } from 'react'

import { useSystemDiagnostics } from '../hooks/useSystemDiagnostics'
import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
  type SystemDiagnostics as SystemDiagnosticsMetrics,
} from '../types/telemetry'

const METRICS = [
  { key: 'cpu' as const, label: 'CPU' },
  { key: 'ram' as const, label: 'RAM' },
  { key: 'disk' as const, label: 'Disk' },
] as const

function resolveDiagnostics(
  diagnostics: SystemDiagnosticsMetrics | null | undefined,
): SystemDiagnosticsMetrics {
  return diagnostics ?? DEFAULT_SYSTEM_DIAGNOSTICS
}

function clampPercentage(value: number): number {
  return Math.min(100, Math.max(0, value))
}

function isMetricUnavailable(
  value: number | null | undefined,
  isInitializing: boolean,
): boolean {
  return isInitializing || value == null || !Number.isFinite(value)
}

function formatPercentage(
  value: number | null | undefined,
  isInitializing: boolean,
): string {
  if (isMetricUnavailable(value, isInitializing)) {
    return '—%'
  }
  return `${Math.round(clampPercentage(value!))}%`
}

function getBarColorClass(percentage: number): string {
  if (percentage >= 90) {
    return 'bg-[#ef4444] shadow-[0_0_8px_rgba(239,68,68,0.6)] animate-pulse'
  }
  if (percentage >= 80) {
    return 'bg-[#f59e0b] shadow-[0_0_8px_rgba(245,158,11,0.6)]'
  }
  return 'bg-[#3b82f6] shadow-[0_0_8px_rgba(59,130,246,0.6)]'
}

function cpuSubText(
  diagnostics: SystemDiagnosticsMetrics,
  isInitializing: boolean,
): string {
  if (isInitializing || diagnostics.cpu_freq == null) {
    return 'N/A'
  }
  return `${diagnostics.cpu_freq.toFixed(1)} GHz`
}

function ramSubText(
  diagnostics: SystemDiagnosticsMetrics,
  isInitializing: boolean,
): string {
  if (
    isInitializing ||
    diagnostics.ram_used == null ||
    diagnostics.ram_total == null
  ) {
    return 'N/A'
  }
  return `${diagnostics.ram_used.toFixed(1)} / ${diagnostics.ram_total.toFixed(0)} GB`
}

function diskSubText(
  diagnostics: SystemDiagnosticsMetrics,
  isInitializing: boolean,
): string {
  if (
    isInitializing ||
    diagnostics.disk_used == null ||
    diagnostics.disk_total == null
  ) {
    return 'N/A'
  }
  return `${diagnostics.disk_used.toFixed(2)} / ${diagnostics.disk_total.toFixed(1)} GB`
}

function metricSubText(
  key: (typeof METRICS)[number]['key'],
  diagnostics: SystemDiagnosticsMetrics,
  isInitializing: boolean,
): string {
  switch (key) {
    case 'cpu':
      return cpuSubText(diagnostics, isInitializing)
    case 'ram':
      return ramSubText(diagnostics, isInitializing)
    case 'disk':
      return diskSubText(diagnostics, isInitializing)
  }
}

type SystemDiagnosticsProps = {
  isCompact?: boolean
}

export function SystemDiagnostics({
  isCompact = false,
}: SystemDiagnosticsProps): ReactElement {
  const { diagnostics, status } = useSystemDiagnostics()
  const resolvedDiagnostics = resolveDiagnostics(diagnostics)
  const isInitializing = status === 'idle' || status === 'loading'

  if (isCompact) {
    return (
      <section
        className="relative w-full"
        aria-label="System resource utilization"
        data-slot="system-diagnostics"
        data-compact="true"
      >
        <div className="relative w-full z-0 grid grid-cols-3 gap-4 text-[color:var(--hud-text)] select-none">
          {METRICS.map(({ key }) => {
            const rawValue = resolvedDiagnostics[key]
            const unavailable = isMetricUnavailable(rawValue, isInitializing)
            const clampedPct = unavailable
              ? 0
              : clampPercentage(rawValue as number)

            return (
              <div
                key={key}
                className="h-1 min-w-0 overflow-hidden rounded-full border border-white/5 bg-white/5"
              >
                <div
                  className={`h-full rounded-full transition-all duration-1000 ease-in-out ${unavailable ? 'bg-white/10' : getBarColorClass(clampedPct)}`}
                  style={{ width: `${clampedPct}%` }}
                />
              </div>
            )
          })}
        </div>
      </section>
    )
  }

  return (
    <section
      className="relative w-full"
      aria-label="System resource utilization"
      data-slot="system-diagnostics"
    >
      <div className="grid w-full grid-cols-1 gap-6 md:grid-cols-3">
        {METRICS.map(({ key, label }) => {
          const rawValue = resolvedDiagnostics[key]
          const unavailable = isMetricUnavailable(rawValue, isInitializing)
          const clampedPct = unavailable
            ? 0
            : clampPercentage(rawValue as number)

          return (
            <div key={key} className="flex min-w-0 flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-[11px] font-bold uppercase text-zinc-400">
                  {label}
                </span>
                <span className="text-zinc-500">
                  {metricSubText(key, resolvedDiagnostics, isInitializing)}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full border border-white/5 bg-white/5">
                  <div
                    className={`h-full rounded-full transition-all duration-1000 ease-in-out ${unavailable ? 'bg-white/10' : getBarColorClass(clampedPct)}`}
                    style={{ width: `${clampedPct}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs font-semibold text-[color:var(--hud-accent)]">
                  {formatPercentage(rawValue, isInitializing)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
