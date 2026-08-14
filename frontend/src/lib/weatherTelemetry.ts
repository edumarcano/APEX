import type { WeatherConditionArchetype, WeatherTimelinePoint } from '../types/telemetry'

export interface ResolvedWeatherInfo {
  temperatureF: number | null
  apparentTempF: number | null
  tempMaxF: number | null
  tempMinF: number | null
  humidityPct: number | null
  windSpeedMph: number | null
  precipProbabilityMax: number | null
  detail: string
  condition: WeatherConditionArchetype | null
  timeline: WeatherTimelinePoint[]
}

export const DEFAULT_WEATHER_INFO: ResolvedWeatherInfo = {
  temperatureF: null,
  apparentTempF: null,
  tempMaxF: null,
  tempMinF: null,
  humidityPct: null,
  windSpeedMph: null,
  precipProbabilityMax: null,
  detail: '',
  condition: null,
  timeline: [],
}

/**
 * Variable Typography Engine - Telemetry Extractor
 * Parses the integer Fahrenheit token out of the raw atmospheric string.
 * Format: "Current temperature is {temp} degrees with {condition}."
 */
export function resolvePipelineTemperatureF(
  weatherReport: string | undefined | null,
): number | null {
  if (!weatherReport) return null

  const tempMatch = weatherReport.match(/Current temperature is\s+(-?\d+)\s+degrees/)
  if (!tempMatch) return null

  const parsedTemp = parseInt(tempMatch[1], 10)
  return isNaN(parsedTemp) ? null : parsedTemp
}

/**
 * Variable Typography Engine - Description Extractor
 * Isolates the atmospheric condition clause, stripping structural padding.
 * Format: "Current temperature is {temp} degrees with {condition}."
 */
export function resolveWeatherDetail(weatherReport: string | undefined | null): string {
  if (!weatherReport) return 'No Atmospheric Data'

  const conditionMatch = weatherReport.match(/with\s+([^.]+)/)
  if (!conditionMatch) return weatherReport

  return conditionMatch[1]
    .trim()
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/**
 * Micro-climate archetype resolver for per-condition Weather card icons.
 * Matches condition tokens in the atmospheric detail clause (case-insensitive).
 */
export function resolveWeatherCondition(detail: string): WeatherConditionArchetype | null {
  const normalized = detail.trim().toLowerCase()
  if (!normalized) return null

  if (normalized.includes('thunderstorm')) return 'thunderstorm'
  if (
    normalized.includes('rain') ||
    normalized.includes('drizzle') ||
    normalized.includes('shower')
  ) {
    return 'rain'
  }
  if (normalized.includes('cloud') || normalized.includes('overcast')) return 'clouds'
  if (normalized.includes('clear')) {
    const hour = new Date().getHours()
    if (hour < 6 || hour >= 18) return 'clear_night'
    return 'clear_day'
  }

  return null
}

const VALID_ARCHETYPES: readonly WeatherConditionArchetype[] = [
  'clear_day',
  'clear_night',
  'clouds',
  'rain',
  'thunderstorm',
]

/** Prefer typed snapshot weather data; fall back to display_text parsers. */
export function resolveWeatherFromModule(module: {
  display_text: string
  data: Record<string, unknown>
}): ResolvedWeatherInfo {
  const tempFromData =
    typeof module.data.temp_f === 'number' && Number.isFinite(module.data.temp_f)
      ? Math.round(module.data.temp_f)
      : null
  const apparentTempFromData =
    typeof module.data.apparent_temp_f === 'number' && Number.isFinite(module.data.apparent_temp_f)
      ? Math.round(module.data.apparent_temp_f)
      : null
  const tempMaxFromData =
    typeof module.data.temp_max_f === 'number' && Number.isFinite(module.data.temp_max_f)
      ? Math.round(module.data.temp_max_f)
      : null
  const tempMinFromData =
    typeof module.data.temp_min_f === 'number' && Number.isFinite(module.data.temp_min_f)
      ? Math.round(module.data.temp_min_f)
      : null
  const humidityFromData =
    typeof module.data.humidity_pct === 'number' && Number.isFinite(module.data.humidity_pct)
      ? Math.round(module.data.humidity_pct)
      : null
  const windFromData =
    typeof module.data.wind_speed_mph === 'number' && Number.isFinite(module.data.wind_speed_mph)
      ? Math.round(module.data.wind_speed_mph)
      : null
  const precipProbFromData =
    typeof module.data.precip_probability_max === 'number' &&
    Number.isFinite(module.data.precip_probability_max)
      ? Math.round(module.data.precip_probability_max)
      : null

  const rawTimeline = Array.isArray(module.data.timeline) ? module.data.timeline : []
  const timeline: WeatherTimelinePoint[] = rawTimeline
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map((item) => {
      const label = typeof item.label === 'string' ? item.label : ''
      const time = typeof item.time === 'string' ? item.time : ''
      const temp_f =
        typeof item.temp_f === 'number' && Number.isFinite(item.temp_f)
          ? Math.round(item.temp_f)
          : null
      const condition = typeof item.condition === 'string' ? item.condition : 'unknown'
      const archetypeRaw = item.archetype
      const archetype =
        typeof archetypeRaw === 'string' &&
        VALID_ARCHETYPES.includes(archetypeRaw as WeatherConditionArchetype)
          ? (archetypeRaw as WeatherConditionArchetype)
          : 'clouds'
      const precip_prob =
        typeof item.precip_prob === 'number' && Number.isFinite(item.precip_prob)
          ? Math.round(item.precip_prob)
          : 0
      return { label, time, temp_f, condition, archetype, precip_prob }
    })

  const conditionFromData =
    typeof module.data.condition === 'string' ? module.data.condition : null
  const archetypeRaw = module.data.archetype
  const archetype =
    typeof archetypeRaw === 'string' &&
    VALID_ARCHETYPES.includes(archetypeRaw as WeatherConditionArchetype)
      ? (archetypeRaw as WeatherConditionArchetype)
      : null

  const detail = conditionFromData
    ? conditionFromData
        .split(' ')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ')
    : resolveWeatherDetail(module.display_text)

  return {
    temperatureF: tempFromData ?? resolvePipelineTemperatureF(module.display_text),
    apparentTempF: apparentTempFromData,
    tempMaxF: tempMaxFromData,
    tempMinF: tempMinFromData,
    humidityPct: humidityFromData,
    windSpeedMph: windFromData,
    precipProbabilityMax: precipProbFromData,
    detail,
    condition: archetype ?? resolveWeatherCondition(detail),
    timeline,
  }
}
