import type { ReactElement } from 'react'

/** Fixed ring radius in viewBox coordinate units. */
const RING_RADIUS = 35

/** Ring center anchor in viewBox coordinate units. */
const RING_CENTER = 50

/** Stroke width applied to track and indicator paths. */
const RING_STROKE_WIDTH = 6

/**
 * Computes the full stroke circumference for a circular ring path.
 *
 * @param radius - Circle radius in viewBox coordinate units.
 * @returns Circumference length used for strokeDasharray derivation.
 */
function computeRingCircumference(radius: number): number {
  return 2 * Math.PI * radius
}

/**
 * Clamps an incoming percentage to the closed interval [0, 100].
 *
 * @param value - Raw percentage input from caller props.
 * @returns Defensively bounded percentage safe for arc offset math.
 */
function clampPercentage(value: number): number {
  return Math.max(0, Math.min(100, value))
}

/**
 * Derives strokeDashoffset from circumference and clamped fill percentage.
 *
 * @param circumference - Full ring path length from computeRingCircumference.
 * @param clampedPercentage - Bounded percentage on [0, 100].
 * @returns Offset length subtracted from strokeDasharray to reveal fill arc.
 */
function computeStrokeDashoffset(
  circumference: number,
  clampedPercentage: number,
): number {
  return circumference * (1 - clampedPercentage / 100)
}

function isValidPercentage(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/**
 * Props contract for the reusable circular ring gauge graphic.
 */
export interface RingGaugeProps {
  /** Percentage fill value on the closed interval [0, 100]; null when unavailable. */
  percentage: number | null | undefined
  /** Human-readable metric label rendered beneath the numeric readout. */
  label: string
  /** Optional subtitle rendered below the percentage inside the SVG. */
  subText?: string
  /** When true, renders N/A fallback with dashed indicator stroke. */
  isUnavailable?: boolean
  /** Optional utility classes merged onto the root SVG wrapper. */
  className?: string
}

function gaugeStrokeClass(clampedPercentage: number): string {
  if (clampedPercentage >= 90) {
    return 'stroke-[#ef4444] drop-shadow-[0_0_6px_rgba(239,68,68,0.5)]'
  }
  if (clampedPercentage >= 80) {
    return 'stroke-[#f59e0b] drop-shadow-[0_0_6px_rgba(245,158,11,0.5)]'
  }
  return 'stroke-[#3b82f6] drop-shadow-[0_0_6px_rgba(59,130,246,0.3)]'
}

/**
 * Stateless circular ring gauge for system metric visualization.
 * Applies defensive percentage clamping before stroke offset calculation.
 */
export function RingGauge({
  percentage,
  label,
  subText,
  isUnavailable = false,
  className,
}: RingGaugeProps): ReactElement {
  const circumference = computeRingCircumference(RING_RADIUS)
  const hasValidPercentage = isValidPercentage(percentage)
  const showFallback = isUnavailable || !hasValidPercentage
  const clampedPercentage = hasValidPercentage
    ? clampPercentage(percentage)
    : 0
  const strokeDashoffset = computeStrokeDashoffset(
    circumference,
    clampedPercentage,
  )
  const displayValue = showFallback
    ? 'N/A%'
    : `${Math.round(clampedPercentage)}%`

  const svgClassName = ['relative h-full w-full', className]
    .filter(Boolean)
    .join(' ')

  const ringTransform = `rotate(-90 ${RING_CENTER} ${RING_CENTER})`

  const indicatorStrokeDasharray = showFallback ? '4, 4' : `${circumference}`

  const indicatorStrokeDashoffset = showFallback ? 0 : strokeDashoffset

  const indicatorClassName = showFallback
    ? 'stroke-[color:var(--hud-text)] opacity-35'
    : gaugeStrokeClass(clampedPercentage)

  return (
    <svg
      className={svgClassName}
      viewBox="0 0 100 100"
      role="img"
      aria-label={
        showFallback
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
        strokeLinecap={showFallback ? 'butt' : 'round'}
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
          showFallback
            ? 'fill-[color:var(--hud-text)] opacity-50'
            : 'fill-[color:var(--hud-accent)]',
        ].join(' ')}
      >
        {displayValue}
      </text>
      {subText != null && subText !== '' ? (
        <text
          x={50}
          y={62}
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-[color:var(--hud-text)] text-[0.38rem] opacity-60 uppercase tracking-wider"
        >
          {subText}
        </text>
      ) : null}
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
