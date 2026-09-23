import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import { useBriefingPipeline } from './useBriefingPipeline'

describe('useBriefingPipeline.generateFromSnapshot', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('defaults to the existing-snapshot cue context', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'success',
      briefing: 'Ready.',
      telemetry: {},
      digest: {},
      metadata: {},
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useBriefingPipeline())

    await act(async () => {
      await result.current.generateFromSnapshot('snap-current', 'focused')
    })

    expect(fetchMock).toHaveBeenCalledWith(API_ENDPOINTS.briefingsGenerate, expect.objectContaining({
      body: JSON.stringify({
        snapshot_id: 'snap-current',
        mode: 'focused',
        cue_context: 'existing_snapshot',
      }),
    }))
  })

  it('sends the after-refresh cue context when requested', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'success',
      briefing: 'Ready.',
      telemetry: {},
      digest: {},
      metadata: {},
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useBriefingPipeline())

    await act(async () => {
      await result.current.generateFromSnapshot('snap-new', 'structured', 'after_refresh')
    })

    expect(fetchMock).toHaveBeenCalledWith(API_ENDPOINTS.briefingsGenerate, expect.objectContaining({
      body: JSON.stringify({
        snapshot_id: 'snap-new',
        mode: 'structured',
        cue_context: 'after_refresh',
      }),
    }))
  })
})
