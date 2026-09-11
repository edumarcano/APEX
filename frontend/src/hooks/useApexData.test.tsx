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
    expect(result.current.data?.reminders).toBe('No pending reminders.')

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
    expect(result.current.data?.activeReminders).toEqual([REMINDER])
    expect(result.current.data?.reminders).toBe(`Pending Reminders: ${REMINDER.note}`)
  })
})
