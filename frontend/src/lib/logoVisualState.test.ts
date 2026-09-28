import { describe, expect, it } from 'vitest'

import {
  resolveLogoVisualColors,
  resolveOuterShellActivity,
  type LogoVisualStateInput,
} from './logoVisualState'

const BASE: LogoVisualStateInput = {
  activity: null,
  briefingStatus: 'idle',
  isCortexQuerying: false,
  isLocalModelLoading: false,
  isLocalModelLoaded: false,
  isSpeaking: false,
  isTelemetryCollecting: false,
}

describe('resolveOuterShellActivity', () => {
  it.each([
    ['preparing', 'wave'],
    ['collecting', 'wave'],
    ['selecting', 'wave'],
    ['investigating', 'normal'],
    ['synthesizing', 'wave'],
    ['persisting', 'wave'],
    ['briefing_ready', 'normal'],
    ['speech_preparing', 'wave'],
    ['speech_playing', 'normal'],
  ] as const)('maps %s to %s shell', (activity, expected) => {
    expect(resolveOuterShellActivity({ ...BASE, activity })).toBe(expected)
  })

  it('keeps the orange local loading wave above every stage and telemetry collection', () => {
    expect(resolveOuterShellActivity({ ...BASE, activity: 'synthesizing', isLocalModelLoading: true, isTelemetryCollecting: true })).toBe('local_loading')
    expect(resolveOuterShellActivity({ ...BASE, isTelemetryCollecting: true })).toBe('wave')
    expect(resolveOuterShellActivity({ ...BASE, activity: 'speech_playing', isTelemetryCollecting: true })).toBe('normal')
  })
})

describe('resolveLogoVisualColors', () => {
  it.each([
    ['preparing', '57, 255, 136'],
    ['collecting', '57, 255, 136'],
    ['selecting', '57, 255, 136'],
    ['investigating', '168, 85, 247'],
    ['synthesizing', '168, 85, 247'],
    ['persisting', '251, 191, 36'],
    ['briefing_ready', '15, 77, 184'],
    ['speech_preparing', '168, 85, 247'],
    ['speech_playing', '34, 211, 238'],
  ] as const)('uses %s color for the nebula and logo', (activity, expected) => {
    expect(resolveLogoVisualColors({ ...BASE, activity })).toEqual({ atmosphere: expected, logo: expected })
  })

  it('keeps the completed and playback logo glow orange for a resident local model while the nebula follows the activity', () => {
    expect(resolveLogoVisualColors({ ...BASE, activity: 'briefing_ready', isLocalModelLoaded: true })).toEqual({
      atmosphere: '15, 77, 184', logo: '249, 115, 22',
    })
    expect(resolveLogoVisualColors({ ...BASE, activity: 'speech_playing', isLocalModelLoaded: true })).toEqual({
      atmosphere: '34, 211, 238', logo: '249, 115, 22',
    })
  })

  it('lets a current Cortex query replace the static completed briefing indication', () => {
    expect(resolveLogoVisualColors({ ...BASE, activity: 'briefing_ready', isCortexQuerying: true })).toEqual({
      atmosphere: '168, 85, 247', logo: '168, 85, 247',
    })
  })

  it('uses telemetry collection color while a completed briefing is selected, then returns to blue', () => {
    expect(resolveLogoVisualColors({ ...BASE, activity: 'briefing_ready', isTelemetryCollecting: true })).toEqual({
      atmosphere: '57, 255, 136', logo: '57, 255, 136',
    })
    expect(resolveLogoVisualColors({ ...BASE, activity: 'briefing_ready' })).toEqual({
      atmosphere: '15, 77, 184', logo: '15, 77, 184',
    })
  })

  it('uses orange for both glows during actual local model loading without changing the stage color', () => {
    expect(resolveLogoVisualColors({ ...BASE, activity: 'synthesizing', isLocalModelLoading: true })).toEqual({
      atmosphere: '249, 115, 22', logo: '249, 115, 22',
    })
  })

  it('preserves the error, Cortex, telemetry, and standby colors outside semantic activities', () => {
    expect(resolveLogoVisualColors({ ...BASE, briefingStatus: 'error' }).atmosphere).toBe('220, 38, 38')
    expect(resolveLogoVisualColors({ ...BASE, isCortexQuerying: true }).atmosphere).toBe('168, 85, 247')
    expect(resolveLogoVisualColors({ ...BASE, isTelemetryCollecting: true }).atmosphere).toBe('57, 255, 136')
    expect(resolveLogoVisualColors(BASE).atmosphere).toBe('15, 77, 184')
  })

  it('lets active Cortex and telemetry operations take priority over a selected failed briefing', () => {
    expect(resolveLogoVisualColors({ ...BASE, briefingStatus: 'error', isCortexQuerying: true }).atmosphere).toBe('168, 85, 247')
    expect(resolveLogoVisualColors({ ...BASE, briefingStatus: 'error', isTelemetryCollecting: true }).atmosphere).toBe('57, 255, 136')
    expect(resolveLogoVisualColors({ ...BASE, briefingStatus: 'error' }).atmosphere).toBe('220, 38, 38')
  })
})
