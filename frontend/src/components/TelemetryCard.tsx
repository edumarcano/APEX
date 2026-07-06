import {
  Cloud,
  CloudLightning,
  CloudRain,
  Moon,
  Sun,
  type LucideIcon,
} from 'lucide-react'
import type * as React from 'react'

import type { WeatherConditionArchetype } from '../types/telemetry'
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
  australia: 'au',
  bahrain: 'bh',
  belgium: 'be',
  brazil: 'br',
  canada: 'ca',
  china: 'cn',
  hungary: 'hu',
  italy: 'it',
  japan: 'jp',
  mexico: 'mx',
  monaco: 'mc',
  netherlands: 'nl',
  qatar: 'qa',
  'saudi arabia': 'sa',
  singapore: 'sg',
  spain: 'es',
  'united arab emirates': 'ae',
  'united kingdom': 'gb',
  'united states': 'us',
  usa: 'us',
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

  return extractBalancedJsonObject(source, jsonStartIndex)
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

const WEATHER_GLOW_BY_CONDITION: Record<
  WeatherConditionArchetype,
  { bgClass: string; opacityClass: string; animateClass: string }
> = {
  clear_day: {
    bgClass: 'bg-[#F4B22A]',
    opacityClass: 'opacity-25',
    animateClass: 'animate-weather-solar',
  },
  clear_night: {
    bgClass: 'bg-[#4F8FFF]',
    opacityClass: 'opacity-24',
    animateClass: 'animate-weather-night',
  },
  clouds: {
    bgClass: 'bg-[#8EA7C7]',
    opacityClass: 'opacity-16',
    animateClass: 'animate-weather-hover',
  },
  rain: {
    bgClass: 'bg-[#37A6FF]',
    opacityClass: 'opacity-30',
    animateClass: 'animate-weather-breath',
  },
  thunderstorm: {
    bgClass: 'bg-[#4F8FFF]',
    opacityClass: 'opacity-20',
    animateClass: 'animate-weather-surge',
  },
}

const WEATHER_ICON_BY_CONDITION: Record<WeatherConditionArchetype, LucideIcon> = {
  clear_day: Sun,
  clear_night: Moon,
  clouds: Cloud,
  rain: CloudRain,
  thunderstorm: CloudLightning,
}

const weatherIconStyles: Record<WeatherConditionArchetype, React.CSSProperties> = {
  clear_day: {
    color: '#FFD166',
    filter: 'drop-shadow(0 0 6px rgba(255, 209, 102, 0.4))',
  },
  clear_night: {
    color: '#A8C8FF',
    filter: 'drop-shadow(0 0 6px rgba(168, 200, 255, 0.4))',
  },
  clouds: {
    color: '#D0D8E8',
    filter: 'drop-shadow(0 0 5px rgba(208, 216, 232, 0.3))',
  },
  rain: {
    color: '#7DD3FC',
    filter: 'drop-shadow(0 0 6px rgba(125, 211, 252, 0.45))',
  },
  thunderstorm: {
    color: '#FFE082',
    filter: 'drop-shadow(0 0 8px rgba(255, 224, 130, 0.5))',
  },
}

function resolveCardHoverClass(title: string): string {
  const normalized = title.trim()
  if (normalized === 'Weather') return 'hover-weather-bright'
  if (normalized === 'Events' || normalized === 'Next F1 Race') {
    return 'hover-blue-medium'
  }
  if (normalized === 'Reminders') return 'hover-blue-strong'
  return 'hover-blue-subtle'
}

export type TelemetryCardProps = {
  title: string
  icon: LucideIcon
  children?: ReactNode
  /** When set, renders the primary temperature numerical readout with VTE inline weight. */
  primaryTemperatureF?: number | null
  /** Optional raw schedule text source used for F1_DATA parsing. */
  rawScheduleText?: string
  /** Micro-climate archetype for scoped atmospheric background glow. */
  weatherCondition?: WeatherConditionArchetype | null
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'children'>

export function TelemetryCard({
  title,
  icon: Icon,
  children,
  primaryTemperatureF,
  rawScheduleText,
  weatherCondition,
  className,
  ...sectionProps
}: TelemetryCardProps): ReactElement {
  const isScheduleCard = title.trim().toLowerCase() === 'next f1 race'
  const showHeader = title.trim().length > 0

  const headingId = useId()
  const weatherGlow =
    weatherCondition != null ? WEATHER_GLOW_BY_CONDITION[weatherCondition] : null
  const WeatherConditionIcon =
    weatherCondition != null
      ? WEATHER_ICON_BY_CONDITION[weatherCondition]
      : null

  const sectionClassName = [
    'relative flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] hud-glass p-[var(--hud-panel-pad)] transition-all duration-700 ease-in-out',
    resolveCardHoverClass(title),
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
      className={sectionClassName}
      aria-labelledby={showHeader ? headingId : undefined}
    >
      {weatherGlow ? (
        <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden rounded-2xl">
          <div
            className={[
              'weather-glow-core absolute inset-0 blur-[64px] transition-opacity duration-500',
              weatherGlow.bgClass,
              weatherGlow.opacityClass,
              weatherGlow.animateClass,
            ].join(' ')}
            aria-hidden
          />
        </div>
      ) : null}
      <div className="relative z-10 flex h-full min-h-0 flex-col">
      {showHeader ? (
        <header className="mb-4 flex min-h-9 shrink-0 items-center gap-3">
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
      ) : null}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {primaryTemperatureF != null ? (
          <div className="mb-3 flex shrink-0 items-center gap-4">
            <p
              className="tabular-nums text-4xl leading-none tracking-tight text-white"
              style={primaryTemperatureStyle}
              data-vte="primary-temperature-readout"
              aria-label="Current temperature"
            >
              {primaryTemperatureF}°
            </p>
            {weatherCondition != null && WeatherConditionIcon != null ? (
              <WeatherConditionIcon
                className="size-8 shrink-0 transition-all duration-1000 ease-in-out"
                style={weatherIconStyles[weatherCondition]}
                strokeWidth={1.75}
                aria-hidden="true"
              />
            ) : null}
          </div>
        ) : null}
        {isScheduleCard && f1Schedule ? (
          <div className="min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin">
            <div className="space-y-1.5 rounded-xl border border-[color:var(--hud-border-color)] bg-black/20 p-3 text-[color:var(--hud-text)]">
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
                className="shrink-0 leading-none"
              >
                {f1Schedule.countryFlag === CHECKERED_FALLBACK_FLAG ? (
                  <span className="text-lg">{f1Schedule.countryFlag}</span>
                ) : (
                  <img
                    src={`https://cdnjs.cloudflare.com/ajax/libs/flag-icon-css/3.4.6/flags/4x3/${f1Schedule.countryFlag}.svg`}
                    alt={`${f1Schedule.country || 'Unknown'} flag`}
                    className="h-3.5 w-5 rounded object-cover shadow-sm"
                    loading="lazy"
                    decoding="async"
                    onError={(event) => {
                      const flagContainer = event.currentTarget.parentElement
                      if (!flagContainer) return
                      flagContainer.textContent = CHECKERED_FALLBACK_FLAG
                    }}
                  />
                )}
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
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden pr-1 scrollbar-thin flex flex-col">
            {children}
          </div>
        )}
      </div>
      </div>
    </section>
  )
}
