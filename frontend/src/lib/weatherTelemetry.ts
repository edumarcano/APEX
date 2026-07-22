import type { WeatherConditionArchetype } from '../types/telemetry'

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
}): {
  temperatureF: number | null
  detail: string
  condition: WeatherConditionArchetype | null
} {
  const tempFromData =
    typeof module.data.temp_f === 'number' && Number.isFinite(module.data.temp_f)
      ? Math.round(module.data.temp_f)
      : null
  const conditionFromData =
    typeof module.data.condition === 'string' ? module.data.condition : null
  const archetypeRaw = module.data.archetype
  const archetype =
    typeof archetypeRaw === 'string' &&
    VALID_ARCHETYPES.includes(archetypeRaw as WeatherConditionArchetype)
      ? (archetypeRaw as WeatherConditionArchetype)
      : null

  if (tempFromData != null || conditionFromData) {
    const detail = conditionFromData
      ? conditionFromData
          .split(' ')
          .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ')
      : resolveWeatherDetail(module.display_text)
    return {
      temperatureF: tempFromData ?? resolvePipelineTemperatureF(module.display_text),
      detail,
      condition: archetype ?? resolveWeatherCondition(detail),
    }
  }

  const detail = resolveWeatherDetail(module.display_text)
  return {
    temperatureF: resolvePipelineTemperatureF(module.display_text),
    detail,
    condition: resolveWeatherCondition(detail),
  }
}
