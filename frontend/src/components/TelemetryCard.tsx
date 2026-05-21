import type { LucideIcon } from 'lucide-react'
import {
  useId,
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from 'react'

/** Variable Typography Engine — closed interval for ambient temperature (°F). */
export const VTE_TEMP_MIN_F = 40
export const VTE_TEMP_MAX_F = 90

/** Variable Typography Engine — closed interval for primary readout font weight. */
export const VTE_WEIGHT_MIN = 300
export const VTE_WEIGHT_MAX = 800

export type VariableTypographyInput = {
  temperatureFahrenheit: number
}

/**
 * Variable Typography Engine interpolation entry point.
 * Maps temperatureFahrenheit on [VTE_TEMP_MIN_F, VTE_TEMP_MAX_F] to font weight
 * on [VTE_WEIGHT_MIN, VTE_WEIGHT_MAX] for the primary temperature readout.
 */
export function resolveTemperatureFontWeight(
  input: VariableTypographyInput,
): number {
  const temp = input.temperatureFahrenheit

  // 1. Enforce strict boundary clamping
  const clampedTemp = Math.max(VTE_TEMP_MIN_F, Math.min(VTE_TEMP_MAX_F, temp))

  // 2. Compute proportional scalar weight via linear interpolation
  const tempRange = VTE_TEMP_MAX_F - VTE_TEMP_MIN_F
  const weightRange = VTE_WEIGHT_MAX - VTE_WEIGHT_MIN

  const interpolatedWeight = VTE_WEIGHT_MIN + ((clampedTemp - VTE_TEMP_MIN_F) / tempRange) * weightRange

  // 3. Round to avoid partial fractional pixel weights
  return Math.round(interpolatedWeight)
}

export type TelemetryCardProps = {
  title: string
  icon: LucideIcon
  children?: ReactNode
  /** When set, renders the primary temperature numerical readout with VTE inline weight. */
  primaryTemperatureF?: number | null
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'children'>

export function TelemetryCard({
  title,
  icon: Icon,
  children,
  primaryTemperatureF,
  className,
  ...sectionProps
}: TelemetryCardProps): ReactElement {
  const headingId = useId()
  const panelClassName = [
    'rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)]',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const primaryTemperatureStyle: CSSProperties | undefined =
    primaryTemperatureF != null
      ? {
          fontWeight: resolveTemperatureFontWeight({
            temperatureFahrenheit: primaryTemperatureF,
          }),
        }
      : undefined

  return (
    <section
      {...sectionProps}
      className={panelClassName}
      aria-labelledby={headingId}
    >
      <header className="mb-4 flex min-h-9 items-center gap-3">
        <Icon
          className="size-5 shrink-0 text-[color:var(--hud-accent)]"
          strokeWidth={1.75}
          aria-hidden
        />
        <h2
          id={headingId}
          className="min-w-0 truncate text-sm font-semibold leading-none tracking-tight text-[color:var(--hud-text)]"
        >
          {title}
        </h2>
      </header>
      <div className="min-w-0">
        {primaryTemperatureF != null ? (
          <p
            className="mb-3 tabular-nums text-4xl leading-none tracking-tight text-[color:var(--hud-accent)]"
            style={primaryTemperatureStyle}
            data-vte="primary-temperature-readout"
            aria-label="Current temperature"
          >
            {primaryTemperatureF}°
          </p>
        ) : null}
        {children}
      </div>
    </section>
  )
}
