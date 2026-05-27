import type { ReactElement } from 'react'

import { useApexData } from '../hooks/useApexData'
import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
  type SystemDiagnostics,
} from '../types/telemetry'

/** Fixed ring radius in viewBox coordinate units. */
const RING_RADIUS = 35

/** Ring center anchor in viewBox coordinate units. */
const RING_CENTER = 50

/** Stroke width applied to track and indicator paths. */
const RING_STROKE_WIDTH = 6

const METRIC_GAUGES = [
  { key: 'cpu' as const, label: 'CPU Use' },
  { key: 'ram' as const, label: 'RAM Alloc' },
  { key: 'disk' as const, label: 'Disk Pres' },
] as const

function computeRingCircumference(radius: number): number {
  return 2 * Math.PI * radius
}

function clampPercentage(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function computeStrokeDashoffset(
  circumference: number,
  clampedPercentage: number,
): number {
  return circumference * (1 - clampedPercentage / 100)
}

function isValidPercentage(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

interface RingGaugeProps {
  percentage: number | null | undefined
  label: string
  isDisconnected: boolean
  className?: string
}

function RingGauge({
  percentage,
  label,
  isDisconnected,
  className,
}: RingGaugeProps): ReactElement {
  const circumference = computeRingCircumference(RING_RADIUS)
  const hasValidPercentage = isValidPercentage(percentage)
  const clampedPercentage = hasValidPercentage
    ? clampPercentage(percentage)
    : 0
  const strokeDashoffset = computeStrokeDashoffset(
    circumference,
    clampedPercentage,
  )
  const displayValue = isDisconnected || !hasValidPercentage
    ? 'N/A%'
    : `${Math.round(clampedPercentage)}%`

  const svgClassName = ['relative h-full w-full', className]
    .filter(Boolean)
    .join(' ')

  const ringTransform = `rotate(-90 ${RING_CENTER} ${RING_CENTER})`

  const indicatorStrokeDasharray = isDisconnected || !hasValidPercentage
    ? '4, 4'
    : `${circumference}`

  const indicatorStrokeDashoffset = isDisconnected || !hasValidPercentage
    ? 0
    : strokeDashoffset

  const indicatorClassName = isDisconnected || !hasValidPercentage
    ? 'stroke-[color:var(--hud-text)] opacity-35'
    : 'stroke-[color:var(--hud-accent)]'

  return (
    <svg
      className={svgClassName}
      viewBox="0 0 100 100"
      role="img"
      aria-label={
        isDisconnected || !hasValidPercentage
          ? `${label}: unavailable`
          : `${label}: ${clampedPercentage} percent`
      }
    >
      <circle
        cx={RING_CENTER}
        cy={RING_CENTER}
        r={RING_RADIUS}
        fill="none"
        strokeWidth={RING_STROKE_WIDTH}
        className="stroke-[color:var(--hud-border-color)] opacity-60"
        transform={ringTransform}
      />
      <circle
        cx={RING_CENTER}
        cy={RING_CENTER}
        r={RING_RADIUS}
        fill="none"
        strokeWidth={RING_STROKE_WIDTH}
        strokeDasharray={indicatorStrokeDasharray}
        strokeDashoffset={indicatorStrokeDashoffset}
        strokeLinecap={isDisconnected || !hasValidPercentage ? 'butt' : 'round'}
        className={indicatorClassName}
        transform={ringTransform}
      />
      <text
        x={RING_CENTER}
        y={RING_CENTER - 2}
        textAnchor="middle"
        dominantBaseline="middle"
        className={[
          'text-[1.125rem] font-semibold tabular-nums',
          isDisconnected || !hasValidPercentage
            ? 'fill-[color:var(--hud-text)] opacity-50'
            : 'fill-[color:var(--hud-accent)]',
        ].join(' ')}
      >
        {displayValue}
      </text>
      <text
        x={RING_CENTER}
        y={RING_CENTER + 14}
        textAnchor="middle"
        dominantBaseline="middle"
        className="fill-[color:var(--hud-text)] text-[0.5rem] font-medium uppercase tracking-wide opacity-80"
      >
        {label}
      </text>
    </svg>
  )
}

function resolveDiagnostics(
  diagnostics: SystemDiagnostics | null | undefined,
): SystemDiagnostics {
  return diagnostics ?? DEFAULT_SYSTEM_DIAGNOSTICS
}

export function DiagnosticProgress(): ReactElement {
  const { diagnostics, status } = useApexData()
  const isLoading = status === 'loading' || status === 'idle'
  const resolvedDiagnostics = resolveDiagnostics(diagnostics)
  const isDisconnected =
    isLoading &&
    resolvedDiagnostics.cpu === null &&
    resolvedDiagnostics.ram === null &&
    resolvedDiagnostics.disk === null

  return (
    <section
      className="w-full"
      aria-label="System resource utilization"
      data-slot="diagnostic-progress"
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
                isDisconnected={isDisconnected}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
