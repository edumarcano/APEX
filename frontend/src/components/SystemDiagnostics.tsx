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

export function SystemDiagnostics(): ReactElement {
  const { diagnostics, status } = useSystemDiagnostics()
  const resolvedDiagnostics = resolveDiagnostics(diagnostics)
  const isInitializing = status === 'idle' || status === 'loading'

  return (
    <section
      className="w-full"
      aria-label="System resource utilization"
      data-slot="system-diagnostics"
    >
      <div className="grid w-full grid-cols-3 gap-2 sm:gap-4">
        {METRIC_GAUGES.map(({ key, label }) => (
          <div
            key={key}
            className="flex min-w-0 flex-col items-center justify-center"
          >
            <div className="aspect-square w-full max-w-[7rem] sm:max-w-[8rem]">
              <RingGauge
                percentage={resolvedDiagnostics[key]}
                label={label}
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
