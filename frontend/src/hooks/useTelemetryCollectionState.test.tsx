import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useTelemetryCollectionState } from './useTelemetryCollectionState'

describe('useTelemetryCollectionState', () => {
  it('starts collection and can reset it', () => {
    const { result } = renderHook(() => useTelemetryCollectionState())
    expect(result.current.collectionStarted).toBe(false)

    act(() => {
      result.current.startCollection()
    })
    expect(result.current.collectionStarted).toBe(true)

    act(() => {
      result.current.resetCollection()
    })
    expect(result.current.collectionStarted).toBe(false)
  })
})
