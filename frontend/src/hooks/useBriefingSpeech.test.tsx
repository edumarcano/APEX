import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import type { BriefingSpeechState, BriefingSpeechStatus } from '../types/briefings'
import { useBriefingSpeech } from './useBriefingSpeech'

const firstSessionId = '00000000-0000-4000-8000-000000000081'
const secondSessionId = '00000000-0000-4000-8000-000000000082'

function state(
  sessionId: string,
  status: BriefingSpeechStatus,
  errorCode: string | null = status === 'unavailable' ? 'tts_unavailable' : null,
): BriefingSpeechState {
  return {
    session_id: sessionId,
    artifact_sha256: `digest-${sessionId}`,
    status,
    error_code: errorCode,
    engine: 'kokoro',
  }
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useBriefingSpeech', () => {
  it('prepares and plays only after explicit actions, then reports playback completion', async () => {
    vi.useFakeTimers()
    const reads: BriefingSpeechStatus[] = ['not_requested', 'ready', 'ready']
    const writes: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId) && !init?.method) {
        return response(state(firstSessionId, reads.shift() ?? 'ready'))
      }
      if (url === API_ENDPOINTS.briefingSessionSpeechPrepare(firstSessionId)) {
        writes.push(url)
        return response(state(firstSessionId, 'preparing'), 202)
      }
      if (url === API_ENDPOINTS.briefingSessionSpeechPlay(firstSessionId)) {
        writes.push(url)
        return response(state(firstSessionId, 'playing'), 202)
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const { result } = renderHook(() => useBriefingSpeech(firstSessionId, 'automatic'))
    await flush()

    expect(result.current.speech?.status).toBe('not_requested')
    expect(writes).toEqual([])

    await act(async () => { await result.current.prepare() })
    expect(result.current.speech?.status).toBe('preparing')
    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    expect(result.current.speech?.status).toBe('ready')

    await act(async () => { await result.current.play() })
    expect(result.current.speech?.status).toBe('playing')
    expect(result.current.playbackCompleted).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(900) })

    expect(result.current.speech?.status).toBe('ready')
    expect(result.current.playbackCompleted).toBe(true)
    expect(writes).toEqual([
      API_ENDPOINTS.briefingSessionSpeechPrepare(firstSessionId),
      API_ENDPOINTS.briefingSessionSpeechPlay(firstSessionId),
    ])
    expect(writes[0]).not.toContain('force=true')
  })

  it('does not start playback when reopening an already prepared session', async () => {
    const requests: Array<{ url: string; method?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      requests.push({ url, method: init?.method })
      return response(state(firstSessionId, 'ready'))
    }))

    const { result } = renderHook(() => useBriefingSpeech(firstSessionId, 'automatic'))
    await waitFor(() => expect(result.current.speech?.status).toBe('ready'))

    expect(requests).toEqual([{ url: API_ENDPOINTS.briefingSessionSpeech(firstSessionId), method: undefined }])
  })

  it('allows an explicit audio recreation request from a ready session', async () => {
    const writes: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId) && !init?.method) return response(state(firstSessionId, 'ready'))
      if (url === API_ENDPOINTS.briefingSessionSpeechPrepare(firstSessionId, true)) {
        writes.push(url)
        return response(state(firstSessionId, 'ready'))
      }
      writes.push(url)
      return response(state(firstSessionId, 'ready'))
    }))
    const { result } = renderHook(() => useBriefingSpeech(firstSessionId, 'manual'))
    await waitFor(() => expect(result.current.speech?.status).toBe('ready'))

    await act(async () => { await result.current.recreateAudio() })

    expect(writes).toEqual([`${API_ENDPOINTS.briefingSessionSpeechPrepare(firstSessionId)}?force=true`])
    expect(result.current.speech?.status).toBe('ready')
  })

  it('keeps cached audio ready after a playback failure without reporting completion', async () => {
    vi.useFakeTimers()
    let reads = 0
    const writes: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId) && !init?.method) {
        reads += 1
        return response(reads === 1 ? state(firstSessionId, 'ready') : state(firstSessionId, 'ready', 'speaker_busy'))
      }
      if (url === API_ENDPOINTS.briefingSessionSpeechPlay(firstSessionId)) {
        writes.push(url)
        return response(state(firstSessionId, 'playing'), 202)
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const { result } = renderHook(() => useBriefingSpeech(firstSessionId, 'manual'))
    await flush()

    await act(async () => { await result.current.play() })
    await act(async () => { await vi.advanceTimersByTimeAsync(900) })

    expect(writes).toEqual([API_ENDPOINTS.briefingSessionSpeechPlay(firstSessionId)])
    expect(result.current.speech).toMatchObject({ status: 'ready', error_code: 'speaker_busy' })
    expect(result.current.playbackCompleted).toBe(false)
  })

  it('stops active speech for the old session when a different session is selected', async () => {
    const requests: Array<{ url: string; method?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      requests.push({ url, method: init?.method })
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId)) return response(state(firstSessionId, 'playing'))
      if (url === API_ENDPOINTS.briefingSessionSpeech(secondSessionId)) return response(state(secondSessionId, 'not_requested'))
      if (url === API_ENDPOINTS.briefingSessionSpeechStop(firstSessionId)) return response(state(firstSessionId, 'stopping'), 202)
      throw new Error(`Unexpected request: ${url}`)
    }))
    const { result, rerender } = renderHook(
      ({ sessionId }) => useBriefingSpeech(sessionId, 'manual'),
      { initialProps: { sessionId: firstSessionId } },
    )
    await waitFor(() => expect(result.current.speech?.status).toBe('playing'))

    rerender({ sessionId: secondSessionId })
    await waitFor(() => expect(result.current.speech?.session_id).toBe(secondSessionId))

    expect(requests.filter((request) => request.url === API_ENDPOINTS.briefingSessionSpeechStop(firstSessionId))).toEqual([
      { url: API_ENDPOINTS.briefingSessionSpeechStop(firstSessionId), method: 'POST' },
    ])
    expect(requests.some((request) => request.url === API_ENDPOINTS.briefingSessionSpeechStop(secondSessionId))).toBe(false)
  })

  it('cancels stale status reads when the selected session changes', async () => {
    let resolveFirst!: (value: Response) => void
    const firstRead = new Promise<Response>((resolve) => { resolveFirst = resolve })
    const signals: AbortSignal[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId)) {
        signals.push(init?.signal as AbortSignal)
        return firstRead
      }
      if (url === API_ENDPOINTS.briefingSessionSpeech(secondSessionId)) return Promise.resolve(response(state(secondSessionId, 'ready')))
      throw new Error(`Unexpected request: ${url}`)
    }))
    const { result, rerender } = renderHook(
      ({ sessionId }) => useBriefingSpeech(sessionId, 'manual'),
      { initialProps: { sessionId: firstSessionId } },
    )
    await flush()
    rerender({ sessionId: secondSessionId })
    await waitFor(() => expect(result.current.speech?.session_id).toBe(secondSessionId))

    expect(signals[0]?.aborted).toBe(true)
    await act(async () => { resolveFirst(response(state(firstSessionId, 'ready'))); await firstRead })
    expect(result.current.speech?.session_id).toBe(secondSessionId)
    expect(result.current.speech?.status).toBe('ready')
  })

  it('stops again when a stale prepare request is admitted after the immediate stop', async () => {
    let resolvePrepare!: (value: Response) => void
    const prepareResponse = new Promise<Response>((resolve) => { resolvePrepare = resolve })
    let prepareSignal: AbortSignal | undefined
    let stopRequests = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId)) return Promise.resolve(response(state(firstSessionId, 'not_requested')))
      if (url === API_ENDPOINTS.briefingSessionSpeech(secondSessionId)) return Promise.resolve(response(state(secondSessionId, 'not_requested')))
      if (url === API_ENDPOINTS.briefingSessionSpeechPrepare(firstSessionId)) {
        prepareSignal = init?.signal as AbortSignal
        return prepareResponse
      }
      if (url === API_ENDPOINTS.briefingSessionSpeechStop(firstSessionId)) {
        stopRequests += 1
        return Promise.resolve(response(state(firstSessionId, 'stopping'), 202))
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const { result, rerender } = renderHook(
      ({ sessionId }) => useBriefingSpeech(sessionId, 'manual'),
      { initialProps: { sessionId: firstSessionId } },
    )
    await waitFor(() => expect(result.current.speech?.status).toBe('not_requested'))

    let prepareRequest!: Promise<void>
    act(() => { prepareRequest = result.current.prepare() })
    await waitFor(() => expect(prepareSignal).toBeDefined())
    rerender({ sessionId: secondSessionId })
    await waitFor(() => expect(result.current.speech?.session_id).toBe(secondSessionId))
    await waitFor(() => expect(stopRequests).toBe(1))
    expect(prepareSignal?.aborted).toBe(false)

    await act(async () => {
      resolvePrepare(response(state(firstSessionId, 'preparing'), 202))
      await prepareRequest
    })
    await waitFor(() => expect(stopRequests).toBe(2))
    expect(result.current.speech).toMatchObject({ session_id: secondSessionId, status: 'not_requested' })
    expect(result.current.pendingAction).toBeNull()
  })

  it('blocks prepare and play when voice mode is off', async () => {
    const writes: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessionSpeech(firstSessionId)) return response(state(firstSessionId, 'ready'))
      writes.push(url)
      return response(state(firstSessionId, 'playing'), 202)
    }))
    const { result } = renderHook(() => useBriefingSpeech(firstSessionId, 'off'))
    await waitFor(() => expect(result.current.speech?.status).toBe('ready'))

    await act(async () => {
      await result.current.prepare()
      await result.current.play()
    })

    expect(result.current.voiceEnabled).toBe(false)
    expect(writes).toEqual([])
  })
})
