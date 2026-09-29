import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import type { BriefingEvidence, BriefingProfileSummary, BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'
import { useBriefingSessions } from './useBriefingSessions'

const sessionId = '00000000-0000-4000-8000-000000000001'
const evidenceId = '00000000-0000-4000-8000-000000000005'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const summary: BriefingSessionSummary = {
  id: sessionId,
  profile_id: 'daily',
  model_id: 'demo/daily-fixture',
  conversation_id: '00000000-0000-4000-8000-000000000002',
  run_id: '00000000-0000-4000-8000-000000000003',
  run_status: 'completed',
  created_at: '2026-09-25T13:00:00Z',
  presented_at: null,
}

function detail(runStatus: BriefingSessionDetail['run_status'] = 'completed'): BriefingSessionDetail {
  return {
    id: sessionId,
    conversation_id: summary.conversation_id,
    opening_message_id: '00000000-0000-4000-8000-000000000004',
    run_id: summary.run_id,
    run_status: runStatus,
    run_error_code: null,
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'A concise view of current information.', definition_version: 2 },
      model: { model_id: summary.model_id, provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'demo',
    },
    artifact: runStatus === 'completed' ? {
      schema_version: 1,
      session_id: sessionId,
      created_at: summary.created_at,
      sections: [{ id: 'section-1', title: 'Today', items: [{
        id: 'item-1', category: 'observation', title: 'Weather', body: 'Clear today.', evidence_ids: [evidenceId], record_references: [],
      }] }],
      coverage: [],
      limitations: [],
    } : null,
    evidence_count: runStatus === 'completed' ? 1 : 0,
    evidence_ids: runStatus === 'completed' ? [evidenceId] : [],
    created_at: summary.created_at,
    presented_at: null,
    speech_status: 'not_requested',
  }
}

const evidence: BriefingEvidence = {
  id: evidenceId,
  source: 'weather',
  source_id: 'weather:current',
  identity_kind: 'provider',
  revision: 'revision-1',
  revision_kind: 'content',
  observed_at: summary.created_at,
  effective_at: null,
  trust: 'observed',
  content: 'Clear, 72F.',
  record_reference: null,
  included_in_synthesis: true,
  available: true,
  unavailable_reason: null,
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useBriefingSessions', () => {
  it('loads the saved artifact independently and fetches one evidence record only when requested', async () => {
    const requested: string[] = []
    let evidenceReads = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      requested.push(url)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([summary])
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      if (url === API_ENDPOINTS.briefingSessionEvidence(sessionId, evidenceId)) {
        evidenceReads += 1
        return response(evidence)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.isLoadingSessions).toBe(false))

    await act(async () => { await result.current.openSession(sessionId) })
    expect(result.current.activeSession?.artifact?.sections[0]?.items[0]?.title).toBe('Weather')
    expect(evidenceReads).toBe(0)

    await act(async () => { await result.current.loadEvidence(sessionId, evidenceId) })
    expect(result.current.evidenceById[evidenceId]?.content).toBe('Clear, 72F.')
    expect(evidenceReads).toBe(1)
    expect(requested.filter((url) => url.includes('/evidence/'))).toHaveLength(1)
  })

  it('renders only the bounded preview event and clears it on a repair reset', async () => {
    const runningSummary = { ...summary, run_status: 'running' as const }
    const preview = [{ title: 'Today', items: [{ category: 'observation', title: 'Weather', body: 'Clear.' }] }]
    const events = [
      { sequence: 1, run_id: summary.run_id, type: 'run.snapshot', timestamp: summary.created_at, payload: { briefing_preview: preview, run: { status: 'running' }, answer: '', activity_steps: [] } },
      { sequence: 2, run_id: summary.run_id, type: 'briefing.preview', timestamp: summary.created_at, payload: { reset: true, sections: [] } },
      { sequence: 3, run_id: summary.run_id, type: 'run.completed', timestamp: summary.created_at, payload: { status: 'failed' } },
    ]
    const encoder = new TextEncoder()
    let releaseTerminal!: () => void
    const terminalGate = new Promise<void>((resolve) => { releaseTerminal = resolve })
    const streamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        const frame = (event: typeof events[number]): Uint8Array => encoder.encode(`id: ${event.sequence}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
        controller.enqueue(frame(events[0]!))
        void terminalGate.then(() => {
          controller.enqueue(frame(events[1]!))
          controller.enqueue(frame(events[2]!))
          controller.close()
        })
      },
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([runningSummary])
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail('running'))
      if (url === API_ENDPOINTS.cortexRunEvents(summary.run_id)) return new Response(streamBody, { headers: { 'Content-Type': 'text/event-stream' } })
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result, unmount } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.sessions).toHaveLength(1))
    await act(async () => { await result.current.openSession(sessionId) })
    await waitFor(() => expect(result.current.preview?.sections).toEqual(preview))
    await act(async () => { releaseTerminal() })
    await waitFor(() => expect(result.current.preview).toBeNull())
    unmount()
  })

  it('loads the newest saved detail for Repeat without changing the displayed session selection', async () => {
    const newestId = '00000000-0000-4000-8000-000000000099'
    const newestSummary: BriefingSessionSummary = {
      ...summary,
      id: newestId,
      profile_id: 'catch_up',
      model_id: 'openai/o4-mini',
      run_status: 'failed',
    }
    const newestDetail: BriefingSessionDetail = {
      ...detail('failed'),
      id: newestId,
      run_status: 'failed',
      run_error_code: 'provider_error',
      configuration: {
        profile: { id: 'catch_up', label: 'Catch Up', purpose: 'Changes since the last briefing.', definition_version: 2 },
        model: { model_id: 'openai/o4-mini', provider: 'openai', runtime: 'cloud', reasoning: 'high', context_window: null, local_reasoning_mode: null },
        origin: 'cli',
        execution_kind: 'model',
      },
      artifact: null,
      evidence_count: 0,
      evidence_ids: [],
      created_at: '2026-09-26T13:00:00Z',
    }
    const requested: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      requested.push(url)
      if (url === API_ENDPOINTS.briefingProfiles) return response([])
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([summary])
      if (url === API_ENDPOINTS.briefingSessions({ limit: 1 })) return response([newestSummary])
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      if (url === API_ENDPOINTS.briefingSession(newestId)) return response(newestDetail)
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.isLoadingSessions).toBe(false))
    await act(async () => { await result.current.openSession(sessionId) })

    await act(async () => { await result.current.refreshLatestSession() })

    expect(result.current.latestSession).toMatchObject({ id: newestId, run_status: 'failed', configuration: { origin: 'cli' } })
    expect(result.current.selectedSessionId).toBe(sessionId)
    expect(result.current.activeSession?.id).toBe(sessionId)
    expect(requested).toContain(API_ENDPOINTS.briefingSessions({ limit: 1 }))
  })

  it('clears a selected session and latest artifact when refresh no longer lists it', async () => {
    let listed: BriefingSessionSummary[] = [summary]
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response(listed)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 1 })) return response(listed.slice(0, 1))
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.sessions).toHaveLength(1))
    await act(async () => { await result.current.openSession(sessionId) })
    expect(result.current.activeSession?.id).toBe(sessionId)

    listed = []
    await act(async () => { await result.current.refreshSessions() })

    expect(result.current.sessions).toEqual([])
    expect(result.current.selectedSessionId).toBeNull()
    expect(result.current.activeSession).toBeNull()
    expect(result.current.latestSession).toBeNull()
  })

  it('does not let an older list response reinsert a session hidden by a newer refresh', async () => {
    let listed: BriefingSessionSummary[] = [summary]
    let releaseOlderList!: (value: Response) => void
    let holdNextList = false
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) {
        if (holdNextList) {
          holdNextList = false
          return new Promise<Response>((resolve) => { releaseOlderList = resolve })
        }
        return response(listed)
      }
      if (url === API_ENDPOINTS.briefingSessions({ limit: 1 })) return response(listed.slice(0, 1))
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.sessions).toHaveLength(1))
    holdNextList = true
    let olderRefresh!: Promise<void>
    act(() => { olderRefresh = result.current.refreshSessions() })
    await waitFor(() => expect(releaseOlderList).toBeTypeOf('function'))

    listed = []
    await act(async () => { await result.current.refreshSessions() })
    releaseOlderList(response([summary]))
    await act(async () => { await olderRefresh })

    expect(result.current.sessions).toEqual([])
  })

  it('reports a failed latest-history check instead of leaving Repeat in a loading state', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response({ detail: 'history unavailable' }, 503)
      if (url === API_ENDPOINTS.briefingProfiles) return response([])
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())

    await waitFor(() => expect(result.current.isLoadingSessions).toBe(false))

    expect(result.current.isLoadingLatestSession).toBe(false)
    expect(result.current.latestError).toBe('history unavailable')
  })

  it('continues polling an active session after the operator selects an older completed session', async () => {
    vi.useFakeTimers()
    const olderId = '00000000-0000-4000-8000-000000000006'
    const activeId = '00000000-0000-4000-8000-000000000007'
    const olderSummary = {
      ...summary,
      id: olderId,
      conversation_id: '00000000-0000-4000-8000-000000000008',
      run_id: '00000000-0000-4000-8000-000000000009',
    }
    const activeSummary = {
      ...summary,
      id: activeId,
      conversation_id: '00000000-0000-4000-8000-000000000010',
      run_id: '00000000-0000-4000-8000-000000000011',
      run_status: 'running' as const,
    }
    const olderDetail = {
      ...detail(),
      id: olderId,
      conversation_id: olderSummary.conversation_id,
      run_id: olderSummary.run_id,
    }
    let activeReads = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([activeSummary, olderSummary])
      if (url === API_ENDPOINTS.briefingProfiles) return response([])
      if (url === API_ENDPOINTS.briefingSession(olderId)) return response(olderDetail)
      if (url === API_ENDPOINTS.briefingSession(activeId)) {
        activeReads += 1
        const status = activeReads >= 3 ? 'completed' : 'running'
        return response({
          ...detail(status),
          id: activeId,
          conversation_id: activeSummary.conversation_id,
          run_id: activeSummary.run_id,
          configuration: {
            ...detail(status).configuration,
            model: { ...detail(status).configuration.model, model_id: activeSummary.model_id },
          },
          active_stage: status === 'completed'
            ? null
            : { stage: activeReads === 1 ? 'collecting' : 'synthesizing', state: 'started' },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(result.current.hasActiveSession).toBe(true)
    expect(activeReads).toBe(1)
    expect(result.current.activeRunDetail?.active_stage?.stage).toBe('collecting')

    await act(async () => { await result.current.openSession(olderId) })
    expect(result.current.selectedSessionId).toBe(olderId)
    expect(result.current.activeSession?.id).toBe(olderId)
    expect(result.current.activeRunDetail?.active_stage?.stage).toBe('collecting')

    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    expect(activeReads).toBe(2)
    expect(result.current.hasActiveSession).toBe(true)
    expect(result.current.activeRunDetail?.active_stage?.stage).toBe('synthesizing')
    expect(result.current.selectedSessionId).toBe(olderId)
    expect(result.current.activeSession?.id).toBe(olderId)

    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    expect(activeReads).toBe(3)
    expect(result.current.sessions.find((session) => session.id === activeId)?.run_status).toBe('completed')
    expect(result.current.hasActiveSession).toBe(false)
    expect(result.current.activeRunDetail).toBeNull()
    expect(result.current.selectedSessionId).toBe(olderId)
    expect(result.current.activeSession?.id).toBe(olderId)
  })

  it('retains an idempotency key after an ambiguous admission failure for an explicit retry', async () => {
    const requestKeys: string[] = []
    let posts = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([])
      if (url === API_ENDPOINTS.briefingSessions() && init?.method === 'POST') {
        posts += 1
        const body = JSON.parse(String(init.body)) as { idempotency_key: string }
        requestKeys.push(body.idempotency_key)
        if (posts === 1) throw new TypeError('Network connection lost after admission.')
        return response({ ...summary, run_status: 'running' }, 202)
      }
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail('running'))
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result, unmount } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.isLoadingSessions).toBe(false))
    const options = { modelId: 'demo/daily-fixture' }

    await act(async () => {
      await expect(result.current.generate('daily', options)).rejects.toThrow('Network connection lost')
    })
    await act(async () => {
      await expect(result.current.generate('daily', options)).resolves.toMatchObject({ id: sessionId })
    })

    expect(requestKeys).toHaveLength(2)
    expect(requestKeys[0]).toBe(requestKeys[1])
    expect(result.current.hasActiveSession).toBe(true)
    unmount()
  })

  it('clears the previous artifact while a newly admitted session loads', async () => {
    const newId = '00000000-0000-4000-8000-000000000006'
    const nextSummary = { ...summary, id: newId, run_status: 'running' as const }
    let releaseDetail!: (value: Response) => void
    const newDetail = new Promise<Response>((resolve) => { releaseDetail = resolve })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([summary])
      if (url === API_ENDPOINTS.briefingSessions() && init?.method === 'POST') return response(nextSummary, 202)
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      if (url === API_ENDPOINTS.briefingSession(newId)) return newDetail
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result, unmount } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.sessions).toHaveLength(1))
    await act(async () => { await result.current.openSession(sessionId) })
    expect(result.current.activeSession?.id).toBe(sessionId)

    await act(async () => { await result.current.generate('daily', { modelId: 'demo/daily-fixture' }) })
    expect(result.current.selectedSessionId).toBe(newId)
    expect(result.current.activeSession).toBeNull()
    expect(result.current.hasActiveSession).toBe(true)

    releaseDetail(response({ ...detail('running'), id: newId }))
    await waitFor(() => expect(result.current.activeSession?.id).toBe(newId))
    unmount()
  })

  it('exposes the profile catalog and sends the chosen profile when generating', async () => {
    const profiles: BriefingProfileSummary[] = [
      { id: 'daily', label: 'Daily', purpose: 'Current view.', investigation_required: false, available: true, unavailable_reason: null },
      { id: 'catch_up', label: 'Catch Up', purpose: 'Changes.', investigation_required: false, available: true, unavailable_reason: null },
    ]
    const sentProfiles: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingProfiles) return response(profiles)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([])
      if (url === API_ENDPOINTS.briefingSessions() && init?.method === 'POST') {
        sentProfiles.push((JSON.parse(String(init.body)) as { profile_id: string }).profile_id)
        return response({ ...summary, profile_id: 'catch_up' }, 202)
      }
      if (url === API_ENDPOINTS.briefingSession(sessionId)) return response(detail())
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.profiles).toEqual(profiles))

    await act(async () => { await result.current.generate('catch_up', { modelId: 'demo/daily-fixture' }) })
    expect(sentProfiles).toEqual(['catch_up'])
  })

  it('keeps sessions usable when the profile catalog cannot load', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === API_ENDPOINTS.briefingProfiles) return response({ detail: 'down' }, 503)
      if (url === API_ENDPOINTS.briefingSessions({ limit: 50 })) return response([summary])
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useBriefingSessions())
    await waitFor(() => expect(result.current.sessions).toHaveLength(1))
    expect(result.current.profiles).toEqual([])
    expect(result.current.error).toBeNull()
  })
})
