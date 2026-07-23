import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useVoiceDelivery } from './useVoiceDelivery'

describe('useVoiceDelivery', () => {
  afterEach(() => vi.restoreAllMocks())

  it('tracks delivery and reports success', async () => {
    let resolveFetch: ((value: Response) => void) | undefined
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve })))
    const { result } = renderHook(() => useVoiceDelivery())

    let request: Promise<boolean>
    act(() => {
      request = result.current.speak('Replay this briefing.')
    })
    expect(result.current.isSpeaking).toBe(true)

    await act(async () => {
      resolveFetch?.(new Response(JSON.stringify({ status: 'spoken' }), { status: 200 }))
      expect(await request!).toBe(true)
    })
    expect(result.current.isSpeaking).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('surfaces stable backend delivery failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Speech delivery is already in progress.' }), { status: 409 }),
    ))
    const { result } = renderHook(() => useVoiceDelivery())

    await act(async () => {
      expect(await result.current.speak('Replay this briefing.')).toBe(false)
    })
    expect(result.current.error).toBe('Speech delivery is already in progress.')
    expect(result.current.isSpeaking).toBe(false)
  })
})
