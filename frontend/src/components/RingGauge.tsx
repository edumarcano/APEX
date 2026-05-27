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

/**
 * Props contract for the reusable sports metric ring gauge graphic.
 */
export interface RingGaugeProps {
  /** Percentage fill value on the closed interval [0, 100]. */
  percentage: number
  /** Human-readable metric label rendered beneath the numeric readout. */
  label: string
  /** Optional utility classes merged onto the root SVG wrapper. */
  className?: string
}

/**
 * Stateless circular ring gauge for sports metric visualization.
 * Applies defensive percentage clamping before stroke offset calculation.
 */
export function RingGauge({
  percentage,
  label,
  className,
}: RingGaugeProps): ReactElement {
  const clampedPercentage = clampPercentage(percentage)
  const circumference = computeRingCircumference(RING_RADIUS)
  const strokeDashoffset = computeStrokeDashoffset(
    circumference,
    clampedPercentage,
  )

  const svgClassName = ['relative h-full w-full', className]
    .filter(Boolean)
    .join(' ')

  const ringTransform = `rotate(-90 ${RING_CENTER} ${RING_CENTER})`

  return (
    <svg
      className={svgClassName}
      viewBox="0 0 100 100"
      role="img"
      aria-label={`${label}: ${clampedPercentage} percent`}
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
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        strokeLinecap="round"
        className="stroke-[color:var(--hud-accent)]"
        transform={ringTransform}
      />
      <text
        x={RING_CENTER}
        y={RING_CENTER - 2}
        textAnchor="middle"
        dominantBaseline="middle"
        className="fill-[color:var(--hud-accent)] text-[1.125rem] font-semibold tabular-nums"
      >
        {Math.round(clampedPercentage)}%
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
