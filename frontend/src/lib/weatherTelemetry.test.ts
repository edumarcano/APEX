import { describe, expect, it } from 'vitest'
import {
  DEFAULT_WEATHER_INFO,
  resolvePipelineTemperatureF,
  resolveWeatherCondition,
  resolveWeatherDetail,
  resolveWeatherFromModule,
} from './weatherTelemetry'

describe('weatherTelemetry', () => {
  it('extracts pipeline temperature from string', () => {
    expect(
      resolvePipelineTemperatureF('Current temperature is 72 degrees with clear sky.'),
    ).toBe(72)
    expect(
      resolvePipelineTemperatureF('Current temperature is -5 degrees with snow.'),
    ).toBe(-5)
    expect(resolvePipelineTemperatureF(null)).toBeNull()
    expect(resolvePipelineTemperatureF('Invalid report format')).toBeNull()
  })

  it('extracts condition detail from string', () => {
    expect(
      resolveWeatherDetail('Current temperature is 72 degrees with partly cloudy.'),
    ).toBe('Partly Cloudy')
    expect(resolveWeatherDetail(null)).toBe('No Atmospheric Data')
    expect(resolveWeatherDetail('Clear sky')).toBe('Clear sky')
  })

  it('resolves weather condition archetypes', () => {
    expect(resolveWeatherCondition('Thunderstorm with rain')).toBe('thunderstorm')
    expect(resolveWeatherCondition('Heavy rain showers')).toBe('rain')
    expect(resolveWeatherCondition('Dense drizzle')).toBe('rain')
    expect(resolveWeatherCondition('Overcast clouds')).toBe('clouds')
    expect(resolveWeatherCondition('Unknown text')).toBeNull()
  })

  it('resolves enriched weather data from healthy module payload', () => {
    const module = {
      display_text:
        "Current temperature is 71 degrees (feels like 74) with partly cloudy. Today's high is 82, low 64.",
      data: {
        temp_f: 71,
        apparent_temp_f: 74,
        temp_max_f: 82,
        temp_min_f: 64,
        humidity_pct: 58,
        wind_speed_mph: 11,
        precip_probability_max: 45,
        condition: 'partly cloudy',
        archetype: 'clouds',
        location: 'Boston',
        timeline: [
          {
            label: 'NOW',
            time: '12 PM',
            temp_f: 71,
            condition: 'partly cloudy',
            archetype: 'clouds',
            precip_prob: 10,
          },
          {
            label: '+4H',
            time: '4 PM',
            temp_f: 82,
            condition: 'slight rain',
            archetype: 'rain',
            precip_prob: 45,
          },
          {
            label: '+8H',
            time: '8 PM',
            temp_f: 66,
            condition: 'clear sky',
            archetype: 'clear_night',
            precip_prob: 0,
          },
        ],
      },
    }

    const resolved = resolveWeatherFromModule(module)
    expect(resolved.temperatureF).toBe(71)
    expect(resolved.apparentTempF).toBe(74)
    expect(resolved.tempMaxF).toBe(82)
    expect(resolved.tempMinF).toBe(64)
    expect(resolved.humidityPct).toBe(58)
    expect(resolved.windSpeedMph).toBe(11)
    expect(resolved.precipProbabilityMax).toBe(45)
    expect(resolved.detail).toBe('Partly Cloudy')
    expect(resolved.condition).toBe('clouds')
    expect(resolved.timeline).toHaveLength(3)
    expect(resolved.timeline[0]).toEqual({
      label: 'NOW',
      time: '12 PM',
      temp_f: 71,
      condition: 'partly cloudy',
      archetype: 'clouds',
      precip_prob: 10,
    })
    expect(resolved.timeline[1].precip_prob).toBe(45)
  })

  it('falls back to string parsing and DEFAULT_WEATHER_INFO properties when module data is minimal', () => {
    const module = {
      display_text: 'Current temperature is 68 degrees with clear sky.',
      data: {},
    }

    const resolved = resolveWeatherFromModule(module)
    expect(resolved.temperatureF).toBe(68)
    expect(resolved.apparentTempF).toBeNull()
    expect(resolved.tempMaxF).toBeNull()
    expect(resolved.timeline).toEqual([])
    expect(DEFAULT_WEATHER_INFO.temperatureF).toBeNull()
  })
})
