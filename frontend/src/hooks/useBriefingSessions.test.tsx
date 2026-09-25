import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import type { BriefingEvidence, BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'
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

afterEach(() => vi.restoreAllMocks())

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
      await expect(result.current.generateDaily(options)).rejects.toThrow('Network connection lost')
    })
    await act(async () => {
      await expect(result.current.generateDaily(options)).resolves.toMatchObject({ id: sessionId })
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

    await act(async () => { await result.current.generateDaily({ modelId: 'demo/daily-fixture' }) })
    expect(result.current.selectedSessionId).toBe(newId)
    expect(result.current.activeSession).toBeNull()
    expect(result.current.hasActiveSession).toBe(true)

    releaseDetail(response({ ...detail('running'), id: newId }))
    await waitFor(() => expect(result.current.activeSession?.id).toBe(newId))
    unmount()
  })
})
