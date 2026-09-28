import { act, renderHook, waitFor } from '@testing-library/react'
import { startTransition } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import type { ActiveReminder } from '../types/telemetry'
import { useApexData } from './useApexData'

const REMINDER: ActiveReminder = {
  id: 'reminder-1',
  note: 'Review the release checklist',
  source: 'local',
  sync_state: 'synced',
}

function response(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Conflict',
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function envelope(items: ActiveReminder[]) {
  return {
    items,
    source_state: 'live',
    cache_timestamp: null,
    pending_sync_count: 0,
  }
}

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input.toString()
}

describe('useApexData reminder completion', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) {
        return Promise.resolve(response({}))
      }
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') {
        return Promise.resolve(response(envelope([REMINDER])))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps reminders in a loading state until the reminder source responds', async () => {
    let resolveReminders!: (value: Response) => void
    const remindersResponse = new Promise<Response>((resolve) => {
      resolveReminders = resolve
    })
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') return remindersResponse
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    expect(result.current.remindersLoadState).toBe('loading')

    resolveReminders(response(envelope([])))
    await waitFor(() => expect(result.current.remindersLoadState).toBe('loaded'))
    expect(result.current.activeReminders).toEqual([])
  })

  it('settles an invalid initial reminders response as unavailable and recovers on retry', async () => {
    const fetchMock = vi.mocked(fetch)
    let remindersReads = 0
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') {
        remindersReads += 1
        return Promise.resolve(response(remindersReads === 1 ? { malformed: true } : envelope([REMINDER])))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    await waitFor(() => expect(result.current.remindersLoadState).toBe('unavailable'))
    expect(result.current.activeReminders).toEqual([])

    await act(async () => result.current.refreshReminders())
    expect(result.current.remindersLoadState).toBe('loaded')
    expect(result.current.activeReminders).toEqual([REMINDER])
  })

  it('settles a failed initial reminders request as unavailable', async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') return Promise.reject(new Error('offline'))
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    await waitFor(() => expect(result.current.remindersLoadState).toBe('unavailable'))
    expect(result.current.activeReminders).toEqual([])
  })

  it('preserves loaded reminders after a failed retry', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') {
        const readCount = fetchMock.mock.calls.filter(([request, requestInit]) =>
          requestUrl(request) === API_ENDPOINTS.reminders && requestInit?.method !== 'POST',
        ).length
        return readCount === 1
          ? Promise.resolve(response(envelope([REMINDER])))
          : Promise.reject(new Error('offline'))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    await waitFor(() => expect(result.current.remindersLoadState).toBe('loaded'))
    await act(async () => result.current.refreshReminders())

    expect(result.current.remindersLoadState).toBe('loaded')
    expect(result.current.activeReminders).toEqual([REMINDER])
  })

  it('submits completion while the optimistic update is queued and refreshes on success', async () => {
    let resolveCompletion!: (value: Response) => void
    const completionResponse = new Promise<Response>((resolve) => {
      resolveCompletion = resolve
    })
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') {
        const reminderGets = fetchMock.mock.calls.filter(([request, requestInit]) =>
          requestUrl(request) === API_ENDPOINTS.reminders && requestInit?.method !== 'POST',
        ).length
        return Promise.resolve(response(envelope(reminderGets === 1 ? [REMINDER] : [])))
      }
      if (url === API_ENDPOINTS.remindersComplete) return completionResponse
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    await waitFor(() => expect(result.current.activeReminders).toEqual([REMINDER]))

    let completion!: Promise<void>
    startTransition(() => {
      completion = result.current.markReminderAsRead(REMINDER.id)
    })

    expect(fetchMock.mock.calls.filter(([request]) => requestUrl(request) === API_ENDPOINTS.remindersComplete)).toHaveLength(1)

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.activeReminders).toEqual([])

    resolveCompletion(response({}))
    await act(async () => {
      await completion
    })

    expect(fetchMock.mock.calls.filter(([request, requestInit]) =>
      requestUrl(request) === API_ENDPOINTS.reminders && requestInit?.method !== 'POST',
    )).toHaveLength(2)
    expect(result.current.activeReminders).toEqual([])
  })

  it('rejects failed completion and restores the reminder and telemetry', async () => {
    const fetchMock = vi.mocked(fetch)
    let rejectCompletion!: (value: Response) => void
    const completionResponse = new Promise<Response>((resolve) => {
      rejectCompletion = resolve
    })
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input)
      if (url === API_ENDPOINTS.config) return Promise.resolve(response({}))
      if (url === API_ENDPOINTS.reminders && init?.method !== 'POST') return Promise.resolve(response(envelope([REMINDER])))
      if (url === API_ENDPOINTS.remindersComplete) return completionResponse
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useApexData())
    await waitFor(() => expect(result.current.activeReminders).toEqual([REMINDER]))

    let completion!: Promise<void>
    startTransition(() => {
      completion = result.current.markReminderAsRead(REMINDER.id)
    })
    expect(fetchMock.mock.calls.filter(([request]) => requestUrl(request) === API_ENDPOINTS.remindersComplete)).toHaveLength(1)

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.activeReminders).toEqual([])

    rejectCompletion(response({ detail: 'Completion failed' }, false, 409))
    await act(async () => {
      await expect(completion).rejects.toThrow('Could not complete reminder.')
    })

    expect(result.current.activeReminders).toEqual([REMINDER])
  })
})
