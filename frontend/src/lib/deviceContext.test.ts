import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEVICE_CONTEXT_STATUS_TIMEOUT_MS, fetchDeviceContextStatus, locationPermissionErrorMessage, parseDeviceContextStatus } from './deviceContext'

const valid = {
  enabled: true,
  permission: 'granted',
  availability: 'available',
  source: 'device',
  freshness: 'fresh',
  fix_age_seconds: 12.5,
}

describe('device context status contract', () => {
  it('accepts coordinate-free status and rejects coordinate fields', () => {
    expect(parseDeviceContextStatus(valid)).toEqual(valid)
    expect(parseDeviceContextStatus({ ...valid, latitude: 47.6 })).toBeNull()
  })

  it.each([
    ['permission', 'prompt'],
    ['availability', 'late'],
    ['source', 'coordinates'],
    ['freshness', 'old'],
    ['fix_age_seconds', Number.POSITIVE_INFINITY],
    ['fix_age_seconds', -1],
  ])('rejects malformed %s', (key, value) => {
    expect(parseDeviceContextStatus({ ...valid, [key]: value })).toBeNull()
  })

  it('accepts null age and finite denied or timed out states', () => {
    expect(parseDeviceContextStatus({ ...valid, permission: 'denied', availability: 'timed_out', freshness: 'none', source: 'configured', fix_age_seconds: null })).not.toBeNull()
  })

  it.each([
    ['foreground_required', /foreground/],
    ['preferences_unavailable', /saved location preference/],
    ['stale_request', /stale/],
    ['backend_unavailable', /backend is unavailable/],
  ])('maps %s to sanitized user guidance', (code, message) => {
    expect(locationPermissionErrorMessage(new Error(code))).toMatch(message)
  })

  it('fetches status from the established API endpoint and rejects malformed responses', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(valid), { status: 200 }))
    await expect(fetchDeviceContextStatus()).resolves.toEqual(valid)
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/device-context'), { signal: expect.any(AbortSignal) })
    fetchMock.mockResolvedValueOnce(new Response('{"latitude":47.6}', { status: 200 }))
    await expect(fetchDeviceContextStatus()).rejects.toThrow(/malformed/)
  })

  it('aborts a hung status transport at its deadline and clears its timer', async () => {
    vi.useFakeTimers()
    let requestSignal: AbortSignal | undefined
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      requestSignal = init?.signal as AbortSignal
      requestSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
    const request = fetchDeviceContextStatus()
    const outcome = request.then(() => null, (error: unknown) => error)
    await vi.advanceTimersByTimeAsync(DEVICE_CONTEXT_STATUS_TIMEOUT_MS)
    expect(await outcome).toEqual(expect.objectContaining({ message: 'Device location status request timed out.' }))
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(requestSignal?.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })

  it('relays caller cancellation to the transport and removes the relay listener', async () => {
    vi.useFakeTimers()
    const caller = new AbortController()
    const addListener = vi.spyOn(caller.signal, 'addEventListener')
    const removeListener = vi.spyOn(caller.signal, 'removeEventListener')
    let requestSignal: AbortSignal | undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      requestSignal = init?.signal as AbortSignal
      requestSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
    const request = fetchDeviceContextStatus(caller.signal)
    const outcome = request.then(() => null, (error: unknown) => error)
    caller.abort()
    expect(await outcome).toEqual(expect.objectContaining({ name: 'AbortError' }))
    expect(requestSignal?.aborted).toBe(true)
    expect(addListener).toHaveBeenCalledOnce()
    expect(removeListener).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})
