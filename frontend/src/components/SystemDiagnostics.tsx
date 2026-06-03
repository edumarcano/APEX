import type { ReactElement } from 'react'

import { useSystemDiagnostics } from '../hooks/useSystemDiagnostics'
import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
  type SystemDiagnostics as SystemDiagnosticsMetrics,
} from '../types/telemetry'
import { RingGauge } from './RingGauge'

const METRIC_GAUGES = [
  { key: 'cpu' as const, label: 'CPU Use' },
  { key: 'ram' as const, label: 'RAM Alloc' },
  { key: 'disk' as const, label: 'Disk Pres' },
] as const

type DiagnosticsSeverity = 'critical' | 'warning' | 'normal'

function resolveDiagnostics(
  diagnostics: SystemDiagnosticsMetrics | null | undefined,
): SystemDiagnosticsMetrics {
  return diagnostics ?? DEFAULT_SYSTEM_DIAGNOSTICS
}

function isMetricUnavailable(
  value: number | null | undefined,
  isInitializing: boolean,
): boolean {
  return isInitializing || value == null || !Number.isFinite(value)
}

function resolvePanelSeverity(
  diagnostics: SystemDiagnosticsMetrics,
): DiagnosticsSeverity {
  const percentages = [diagnostics.cpu, diagnostics.ram, diagnostics.disk].filter(
    (value): value is number =>
      typeof value === 'number' && Number.isFinite(value),
  )

  if (percentages.some((value) => value >= 90)) {
    return 'critical'
  }
  if (percentages.some((value) => value >= 80)) {
    return 'warning'
  }
  return 'normal'
}

function severityGlowClass(severity: DiagnosticsSeverity): string {
  switch (severity) {
    case 'critical':
      return 'bg-red-500'
    case 'warning':
      return 'bg-amber-500'
    default:
      return 'bg-blue-500'
  }
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
  key: (typeof METRIC_GAUGES)[number]['key'],
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

export function SystemDiagnostics(): ReactElement {
  const { diagnostics, status } = useSystemDiagnostics()
  const resolvedDiagnostics = resolveDiagnostics(diagnostics)
  const isInitializing = status === 'idle' || status === 'loading'
  const severity = resolvePanelSeverity(resolvedDiagnostics)

  return (
    <section
      className="relative w-full overflow-hidden"
      aria-label="System resource utilization"
      data-slot="system-diagnostics"
    >
      <div
        className={`pointer-events-none absolute inset-0 -z-10 blur-xl opacity-[0.06] transition-colors duration-1000 ${severityGlowClass(severity)}`}
        aria-hidden
      />
      <div
        className="-z-10 absolute left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-[#39FF88]/40 to-transparent animate-sensor-sweep"
        aria-hidden
      />
      <div className="relative z-0 grid w-full grid-cols-3 gap-2 sm:gap-4">
        {METRIC_GAUGES.map(({ key, label }) => (
          <div
            key={key}
            className="flex min-w-0 flex-col items-center justify-center"
          >
            <div className="aspect-square w-full max-w-[7rem] sm:max-w-[8rem]">
              <RingGauge
                percentage={resolvedDiagnostics[key]}
                label={label}
                subText={metricSubText(key, resolvedDiagnostics, isInitializing)}
                isUnavailable={isMetricUnavailable(
                  resolvedDiagnostics[key],
                  isInitializing,
                )}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
