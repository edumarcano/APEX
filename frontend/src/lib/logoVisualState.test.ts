import { describe, expect, it } from 'vitest'

import {
  resolveLogoVisualColors,
  resolveOuterShellActivity,
  type LogoVisualStateInput,
} from './logoVisualState'

const BASE: LogoVisualStateInput = {
  briefingStatus: 'idle',
  activeStep: null,
  activated: true,
  isBriefingRunning: false,
  isCortexQuerying: false,
  isLocalModelLoading: false,
  isLocalModelLoaded: false,
  isSpeaking: false,
  isTelemetryCollecting: false,
}

describe('resolveOuterShellActivity', () => {
  it('keeps collection for refreshes and briefing steps one and two', () => {
    expect(resolveOuterShellActivity({ ...BASE, isTelemetryCollecting: true })).toBe('collection')
    expect(resolveOuterShellActivity({ ...BASE, isBriefingRunning: true, activeStep: 2 })).toBe('collection')
  })

  it('suppresses the outer wave during synthesis and gives local loading priority', () => {
    expect(resolveOuterShellActivity({ ...BASE, isBriefingRunning: true, activeStep: 3, isTelemetryCollecting: true })).toBe('synthesis')
    expect(resolveOuterShellActivity({ ...BASE, isBriefingRunning: true, activeStep: 3, isLocalModelLoading: true })).toBe('local_loading')
  })
})

describe('resolveLogoVisualColors', () => {
  it('uses rust for both visual layers while a local model loads', () => {
    expect(resolveLogoVisualColors({ ...BASE, isLocalModelLoading: true })).toEqual({
      atmosphere: '249, 115, 22',
      logo: '249, 115, 22',
    })
  })

  it('keeps atmosphere and logo glow rust while a local model is resident', () => {
    expect(resolveLogoVisualColors({ ...BASE, isLocalModelLoaded: true })).toEqual({
      atmosphere: '249, 115, 22',
      logo: '249, 115, 22',
    })
  })

  it('retains error, query, delivery, and briefing-stage precedence', () => {
    expect(resolveLogoVisualColors({ ...BASE, briefingStatus: 'error', isCortexQuerying: true }).logo).toBe('220, 38, 38')
    expect(resolveLogoVisualColors({ ...BASE, isCortexQuerying: true }).logo).toBe('168, 85, 247')
    expect(resolveLogoVisualColors({ ...BASE, activeStep: 4 }).logo).toBe('251, 191, 36')
    expect(resolveLogoVisualColors({ ...BASE, isBriefingRunning: true, activeStep: 2 }).logo).toBe('57, 255, 136')
  })
})
