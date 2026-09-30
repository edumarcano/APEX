import { describe, expect, it } from 'vitest'

import { resolveConnectorStatus } from './settingsCategories'

describe('Sports runtime connector status', () => {
  it('recognizes only canonical independent sport connector names', () => {
    expect(resolveConnectorStatus('sports', true, ['f1'], true).tone).toBe('error')
    expect(resolveConnectorStatus('sports', true, ['football'], true).tone).toBe('error')
  })

  it('keeps disabled and unchecked Sports status neutral', () => {
    expect(resolveConnectorStatus('sports', false, ['f1'], true).tone).toBe('neutral')
    expect(resolveConnectorStatus('sports', true, ['f1'], false).tone).toBe('neutral')
  })
})
