import { describe, expect, it } from 'vitest'

import { resolveTelemetryAttentionTier } from './attentionTier'

describe('resolveTelemetryAttentionTier', () => {
  it('keeps telemetry dormant until collection starts', () => {
    expect(resolveTelemetryAttentionTier('market', {
      collectionStarted: false, isRefreshing: true, hasSnapshot: true,
      briefingStatus: null, briefingStep: null,
    })).toBe('dormant')
  })

  it('reveals telemetry through collection and keeps briefing stages authoritative', () => {
    expect(resolveTelemetryAttentionTier('weather', {
      collectionStarted: true, isRefreshing: true, hasSnapshot: false,
      briefingStatus: null, briefingStep: null,
    })).toBe('pending')
    expect(resolveTelemetryAttentionTier('market', {
      collectionStarted: true, isRefreshing: false, hasSnapshot: true,
      briefingStatus: 'loading', briefingStep: 2,
    })).toBe('active')
  })
})
