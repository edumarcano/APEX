import { describe, expect, it } from 'vitest'

import { DEFAULT_WEATHER_INFO, resolveWeatherFromModule } from './weatherTelemetry'

describe('weatherTelemetry', () => {
  it('resolves typed weather metrics, condition, archetype, and timeline', () => {
    const module = {
      display_text: 'Current temperature is 999 degrees with thunderstorm.',
      data: {
        temp_f: 71.4,
        apparent_temp_f: 74,
        temp_max_f: 82,
        temp_min_f: 64,
        humidity_pct: 58,
        wind_speed_mph: 11,
        precip_probability_max: 45,
        condition: 'partly cloudy',
        archetype: 'clouds',
        timeline: [
          { label: 'NOW', time: '12 PM', temp_f: 71.4, condition: 'partly cloudy', archetype: 'clouds', precip_prob: 10 },
          { label: '+4H', time: '4 PM', temp_f: Infinity, condition: 'slight rain', archetype: 'rain', precip_prob: 45 },
        ],
      },
    }

    expect(resolveWeatherFromModule(module)).toMatchObject({
      temperatureF: 71,
      apparentTempF: 74,
      tempMaxF: 82,
      tempMinF: 64,
      humidityPct: 58,
      windSpeedMph: 11,
      precipProbabilityMax: 45,
      detail: 'Partly Cloudy',
      condition: 'clouds',
      timeline: [
        { label: 'NOW', time: '12 PM', temp_f: 71, condition: 'partly cloudy', archetype: 'clouds', precip_prob: 10 },
        { label: '+4H', time: '4 PM', temp_f: null, condition: 'slight rain', archetype: 'rain', precip_prob: 45 },
      ],
    })
  })

  it('ignores prose values and missing or invalid typed data', () => {
    const resolved = resolveWeatherFromModule({
      display_text: 'Current temperature is 68 degrees with clear sky.',
      data: {
        temp_f: '68',
        condition: 42,
        archetype: 'snow',
        humidity_pct: Number.NaN,
      },
    })

    expect(resolved.temperatureF).toBeNull()
    expect(resolved.humidityPct).toBeNull()
    expect(resolved.detail).toBe('')
    expect(resolved.condition).toBeNull()
    expect(resolved.timeline).toEqual([])
    expect(DEFAULT_WEATHER_INFO.temperatureF).toBeNull()
    expect(DEFAULT_WEATHER_INFO.detail).toBe('')
  })

  it('uses the supplied clear-sky archetype without prose or local-clock inference', () => {
    const resolveClearArchetype = (archetype: 'clear_day' | 'clear_night') => resolveWeatherFromModule({
      display_text: 'The prose says this is a thunderstorm at every hour.',
      data: { condition: 'clear sky', archetype },
    })

    expect(resolveClearArchetype('clear_day')).toMatchObject({ detail: 'Clear Sky', condition: 'clear_day' })
    expect(resolveClearArchetype('clear_night')).toMatchObject({ detail: 'Clear Sky', condition: 'clear_night' })
  })

  it('labels the active weather location source without exposing device coordinates', () => {
    expect(resolveWeatherFromModule({ display_text: '', data: {
      location_source: 'device', location: 'Current area',
    } })).toMatchObject({
      locationSource: 'device', locationLabel: 'Current area · Device location',
    })
    expect(resolveWeatherFromModule({ display_text: '', data: {
      location_source: 'configured', location: 'Seattle',
    } }).locationLabel).toBe('Seattle · Configured location')
    expect(resolveWeatherFromModule({ display_text: '', data: { location: 'Legacy City' } }).locationLabel).toBeNull()
  })
})
