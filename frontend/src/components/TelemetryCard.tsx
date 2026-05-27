import type { LucideIcon } from 'lucide-react'
import {
  useId,
  useMemo,
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

const F1_DATA_PREFIX = 'F1_DATA:'
const CHECKERED_FALLBACK_FLAG = '🏁'

type F1SchedulePayload = {
  raceName?: unknown
  round?: unknown
  country?: unknown
  raceDateTimeEST?: unknown
  relativeWeek?: unknown
  sprintScheduled?: unknown
  sprintDateTimeEST?: unknown
}

const COUNTRY_FLAG_MAP: Record<string, string> = {
  australia: '🇦🇺',
  bahrain: '🇧🇭',
  belgium: '🇧🇪',
  brazil: '🇧🇷',
  canada: '🇨🇦',
  china: '🇨🇳',
  hungary: '🇭🇺',
  italy: '🇮🇹',
  japan: '🇯🇵',
  mexico: '🇲🇽',
  monaco: '🇲🇨',
  netherlands: '🇳🇱',
  qatar: '🇶🇦',
  'saudi arabia': '🇸🇦',
  singapore: '🇸🇬',
  spain: '🇪🇸',
  'united arab emirates': '🇦🇪',
  'united kingdom': '🇬🇧',
  'united states': '🇺🇸',
  usa: '🇺🇸',
}

function extractBalancedJsonObject(source: string, startIndex: number): string | null {
  if (source[startIndex] !== '{') return null

  let depth = 0
  let inString = false
  let isEscaped = false

  for (let index = startIndex; index < source.length; index += 1) {
    const character = source[index]

    if (inString) {
      if (isEscaped) {
        isEscaped = false
        continue
      }
      if (character === '\\') {
        isEscaped = true
        continue
      }
      if (character === '"') {
        inString = false
      }
      continue
    }

    if (character === '"') {
      inString = true
      continue
    }

    if (character === '{') {
      depth += 1
      continue
    }

    if (character === '}') {
      depth -= 1
      if (depth === 0) {
        return source.slice(startIndex, index + 1)
      }
    }
  }

  return null
}

function extractF1DataJson(source: string): string | null {
  const prefixIndex = source.indexOf(F1_DATA_PREFIX)
  if (prefixIndex < 0) return null

  let jsonStartIndex = prefixIndex + F1_DATA_PREFIX.length
  while (jsonStartIndex < source.length && /\s/.test(source[jsonStartIndex])) {
    jsonStartIndex += 1
  }

  const balancedObject = extractBalancedJsonObject(source, jsonStartIndex)
  if (balancedObject) return balancedObject

  const lineEndIndex = source.indexOf('\n', jsonStartIndex)
  return source
    .slice(
      jsonStartIndex,
      lineEndIndex >= 0 ? lineEndIndex : source.length,
    )
    .trim()
}

function parseF1SchedulePayload(source: string): F1SchedulePayload | null {
  const jsonBlock = extractF1DataJson(source)
  if (!jsonBlock) return null

  try {
    const parsed = JSON.parse(jsonBlock) as unknown
    if (parsed && typeof parsed === 'object') {
      return parsed as F1SchedulePayload
    }
  } catch {
    return null
  }

  return null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false
}

function resolveCountryFlag(country: string): string {
  const normalizedCountry = country.toLowerCase()
  return COUNTRY_FLAG_MAP[normalizedCountry] ?? CHECKERED_FALLBACK_FLAG
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
  /** Optional raw schedule text source used for F1_DATA parsing. */
  rawScheduleText?: string
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'children'>

export function TelemetryCard({
  title,
  icon: Icon,
  children,
  primaryTemperatureF,
  rawScheduleText,
  className,
  ...sectionProps
}: TelemetryCardProps): ReactElement {
  const isScheduleCard = title.trim().toLowerCase() === 'f1 schedule'

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

  const f1Schedule = useMemo(() => {
    if (!isScheduleCard) return null
    const payload = parseF1SchedulePayload(rawScheduleText ?? '')
    if (!payload) return null

    const raceName = asString(payload.raceName) || 'Upcoming Grand Prix'
    const round = asString(payload.round) || 'TBD'
    const country = asString(payload.country)
    const raceDateTimeEST = asString(payload.raceDateTimeEST)
    const relativeWeek = asString(payload.relativeWeek)
    const sprintScheduled = asBoolean(payload.sprintScheduled)
    const sprintDateTimeEST = asString(payload.sprintDateTimeEST)

    return {
      raceName,
      round,
      country,
      raceEtLabel: `${relativeWeek} — ${raceDateTimeEST}`,
      sprintScheduled,
      sprintEtLabel: sprintDateTimeEST,
      countryFlag: resolveCountryFlag(country),
    }
  }, [isScheduleCard, rawScheduleText])

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
        {isScheduleCard && f1Schedule ? (
          <div className="space-y-3 rounded-xl border border-[color:var(--hud-border-color)] bg-black/20 p-4 text-[color:var(--hud-text)]">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold tracking-tight text-[color:var(--hud-text)]">
                  {f1Schedule.raceName}
                </p>
                <p className="text-xs text-[color:var(--hud-muted-text)]">
                  Round {f1Schedule.round}
                </p>
              </div>
              <span
                aria-label={`Race country flag ${f1Schedule.country || 'unknown'}`}
                className="shrink-0 text-xl leading-none"
              >
                {f1Schedule.countryFlag}
              </span>
            </div>

            <p className="text-sm font-medium text-[color:var(--hud-accent)]">
              {f1Schedule.raceEtLabel}
            </p>

            {f1Schedule.sprintScheduled ? (
              <span className="inline-flex items-center rounded-full border border-[color:var(--hud-accent)] px-3 py-1 text-xs font-semibold uppercase tracking-wide text-[color:var(--hud-accent)]">
                Sprint {f1Schedule.sprintEtLabel}
              </span>
            ) : null}
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  )
}
