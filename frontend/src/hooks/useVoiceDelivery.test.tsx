import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SystemState } from '../types/telemetry'
import { useVoiceDelivery } from './useVoiceDelivery'

type VoiceDeliveryInputs = {
  text: string
  status: SystemState
  isPipelineSpeaking: boolean
}

describe('useVoiceDelivery', () => {
  afterEach(() => vi.restoreAllMocks())

  it('tracks delivery and reports success', async () => {
    let resolveFetch: ((value: Response) => void) | undefined
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve })))
    const { result } = renderHook(() => useVoiceDelivery('Replay this briefing.', 'success', false))

    let request: Promise<boolean>
    act(() => {
      request = result.current.speak('Replay this briefing.')
    })
    expect(result.current.isSpeaking).toBe(true)

    await act(async () => {
      resolveFetch?.(new Response(JSON.stringify({ status: 'spoken', resolved_engine: 'pyttsx3' }), { status: 200 }))
      expect(await request!).toBe(true)
    })
    expect(result.current.isSpeaking).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.lastManualEngine).toBe('pyttsx3')
  })

  it('rejects a success response without a valid resolved engine', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'spoken' }), { status: 200 }),
    ))
    const { result } = renderHook(() => useVoiceDelivery('Replay this briefing.', 'success', false))

    await act(async () => {
      expect(await result.current.speak('Replay this briefing.')).toBe(false)
    })
    expect(result.current.error).toBe('Voice delivery returned an invalid engine.')
  })

  it('surfaces stable backend delivery failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Speech delivery is already in progress.' }), { status: 409 }),
    ))
    const { result } = renderHook(() => useVoiceDelivery('Replay this briefing.', 'success', false))

    await act(async () => {
      expect(await result.current.speak('Replay this briefing.')).toBe(false)
    })
    expect(result.current.error).toBe('Speech delivery is already in progress.')
    expect(result.current.isSpeaking).toBe(false)
  })

  it('clears the manual result when a new briefing begins or pipeline speech starts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ status: 'spoken', resolved_engine: 'pyttsx3' }), { status: 200 }),
    )))
    const { result, rerender } = renderHook(
      ({ text, status, isPipelineSpeaking }: VoiceDeliveryInputs) =>
        useVoiceDelivery(text, status, isPipelineSpeaking),
      { initialProps: { text: 'First briefing.', status: 'success', isPipelineSpeaking: false } },
    )

    await act(async () => {
      expect(await result.current.speak('First briefing.')).toBe(true)
    })
    expect(result.current.lastManualEngine).toBe('pyttsx3')

    rerender({ text: 'First briefing.', status: 'loading', isPipelineSpeaking: false })
    expect(result.current.lastManualEngine).toBeNull()

    rerender({ text: 'First briefing.', status: 'success', isPipelineSpeaking: false })
    await act(async () => {
      expect(await result.current.speak('First briefing.')).toBe(true)
    })
    rerender({ text: 'Second briefing.', status: 'success', isPipelineSpeaking: false })
    expect(result.current.lastManualEngine).toBeNull()

    await act(async () => {
      expect(await result.current.speak('Second briefing.')).toBe(true)
    })
    rerender({ text: 'Second briefing.', status: 'success', isPipelineSpeaking: true })
    expect(result.current.lastManualEngine).toBeNull()
  })
})
