import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchDeviceContextStatus, locationPermissionErrorMessage, parseDeviceContextStatus } from './deviceContext'

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
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/device-context'), { signal: undefined })
    fetchMock.mockResolvedValueOnce(new Response('{"latitude":47.6}', { status: 200 }))
    await expect(fetchDeviceContextStatus()).rejects.toThrow(/malformed/)
  })
})

afterEach(() => vi.restoreAllMocks())
