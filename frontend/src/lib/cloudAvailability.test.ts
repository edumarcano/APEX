import { describe, expect, it } from 'vitest'

import type { AgentAvailabilityStatus } from '../types/telemetry'
import { cloudAvailabilityPresentation } from './cloudAvailability'

describe('cloudAvailabilityPresentation', () => {
  it('presents every known backend blocker as an error', () => {
    const blockers: AgentAvailabilityStatus[] = [
      'unauthorized',
      'model_unavailable',
      'rate_limited',
      'quota_exhausted',
      'billing_blocked',
      'provider_unreachable',
      'provider_error',
      'disabled',
    ]

    for (const status of blockers) {
      expect(cloudAvailabilityPresentation(status, true, true).tone).toBe('error')
    }
  })

  it('keeps configured, unknown, and verifying states neutral', () => {
    expect(cloudAvailabilityPresentation('configured', true, true)).toEqual({ label: 'Configured', tone: 'neutral' })
    expect(cloudAvailabilityPresentation('unknown', true, true).tone).toBe('neutral')
    expect(cloudAvailabilityPresentation('verifying', true, true).tone).toBe('neutral')
    expect(cloudAvailabilityPresentation('configured', true, false)).toEqual({ label: 'Browser offline', tone: 'error' })
  })

  it('lets browser offline override successful cloud status but preserves local-only signals', () => {
    expect(cloudAvailabilityPresentation('verified', true, false)).toEqual({ label: 'Browser offline', tone: 'error' })
    expect(cloudAvailabilityPresentation('rate_limited', true, false).label).toBe('Rate limited')
  })
})
