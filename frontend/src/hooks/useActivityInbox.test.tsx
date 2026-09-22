import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useActivityInbox } from './useActivityInbox'

const REPORT = {
  id: 'report-1', partition: 'production', client_id: 'codex', client_display_name: 'Codex', principal: 'operator',
  received_at: '2026-09-21T12:00:00Z', disposition: 'new',
  report: {
    version: '1', submission_key: 'key-1', title: 'Finished work', task_status: 'completed', outcome: 'Focused checks passed.',
    findings: [{ title: 'Check result', text: 'Focused checks passed.', derivation: 'unknown' }], evidence_links: [], artifact_references: [],
    unresolved_questions: [], suggested_follow_up: null, subjects: [], projects: [], occurred_at: null, native_task_url: null, markdown_body: null,
  },
}
const REVIEW = {
  id: 'review-1', partition: 'production', operation: 'capture', proposal: { kind: 'note', text: 'Keep this.' }, evidence: {},
  expected_revisions: {}, reason_codes: ['external_activity'], decision: 'pending', action_id: 'action-1', decision_at: null, created_at: '2026-09-21T12:01:00Z',
}

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

describe('useActivityInbox', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('loads a bounded report, changes only its disposition, and refreshes linked reviews after a proposal', async () => {
    let current = REPORT
    let links: unknown[] = []
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const target = String(input)
      if (target.includes('/context-proposals')) {
        expect(init).toMatchObject({ method: 'POST' })
        links = [{ finding_reference: '/findings/0', review: REVIEW }]
        return response(REVIEW)
      }
      if (target.endsWith('/context-reviews')) return response(links)
      if (target.endsWith('/report-1') && init?.method === 'PATCH') {
        current = { ...REPORT, disposition: 'dismissed' }
        return response(current)
      }
      if (target.endsWith('/report-1')) return response(current)
      if (target.includes('/activity/reports?')) return response([current])
      throw new Error(`Unexpected activity request ${target}`)
    })

    const { result } = renderHook(() => useActivityInbox(true))
    await waitFor(() => expect(result.current.detail?.id).toBe('report-1'))

    await act(async () => { await result.current.setDisposition('dismissed') })
    expect(result.current.detail?.disposition).toBe('dismissed')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/activity/reports/report-1'),
      expect.objectContaining({ method: 'PATCH' }),
    )

    await act(async () => {
      await result.current.proposeContext({ finding_reference: '/findings/0', kind: 'note', text: 'Keep this.' })
    })
    expect(result.current.linkedReviews).toEqual([{ finding_reference: '/findings/0', review: REVIEW }])
  })
})
