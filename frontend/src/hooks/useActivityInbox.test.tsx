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

    const { result } = renderHook(() => useActivityInbox(true, 'production'))
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

  it('clears production records and ignores stale requests when the partition changes', async () => {
    let listRequestCount = 0
    let resolveStaleList: ((value: Response) => void) | undefined
    vi.mocked(fetch).mockImplementation((input) => {
      const target = String(input)
      if (target.endsWith('/context-reviews')) return Promise.resolve(response([]))
      if (target.endsWith('/report-1')) return Promise.resolve(response(REPORT))
      if (!target.includes('/activity/reports?')) throw new Error(`Unexpected activity request ${target}`)
      listRequestCount += 1
      if (listRequestCount === 1) return Promise.resolve(response([REPORT]))
      if (listRequestCount === 2) {
        return new Promise((resolve) => { resolveStaleList = resolve })
      }
      return Promise.reject(new Error('Sandbox activity is unavailable.'))
    })

    const initialProps: { partition: 'production' | 'sandbox' } = { partition: 'production' }
    const { result, rerender } = renderHook(
      ({ partition }: { partition: 'production' | 'sandbox' }) => useActivityInbox(true, partition),
      { initialProps },
    )
    await waitFor(() => expect(result.current.detail?.id).toBe(REPORT.id))

    act(() => { void result.current.refresh() })
    await waitFor(() => expect(resolveStaleList).toBeDefined())
    rerender({ partition: 'sandbox' })

    await waitFor(() => expect(listRequestCount).toBe(3))
    await waitFor(() => expect(result.current.error).toBe('Sandbox activity is unavailable.'))
    await act(async () => {
      resolveStaleList?.(response([REPORT]))
      await Promise.resolve()
    })

    expect(result.current.reports).toEqual([])
    expect(result.current.detail).toBeNull()
    expect(result.current.linkedReviews).toEqual([])
    expect(result.current.selectedReportId).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })
})
