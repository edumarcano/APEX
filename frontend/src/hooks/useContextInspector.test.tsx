import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useContextInspector } from './useContextInspector'

const RECORD = {
  id: 'record-1', partition: 'production', kind: 'note', text: 'Keep the plan concise.', status: 'active',
  subject: null, predicate: null, object_entity: null, object_value: null, effective_at: null,
  supersedes_record_id: null, created_at: '2026-08-18T00:00:00Z', updated_at: '2026-08-18T00:00:00Z',
}
const STATUS = { enabled: true, mode: 'fts_only', state: 'unprepared', indexed_items: 1, embedding_items: 0, pending_items: 1, last_prepared_at: null, error_category: null, model_fingerprint: null }
const ACTION = { action_id: 'action-1', proposal: { capability_name: 'remember_personal_context' }, status: 'proposed', version: 0, updated_at: '2026-08-18T00:00:00Z' }
const DETAIL = { ...RECORD, sources: [], superseded_by: [], related_records: [] }

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

describe('useContextInspector', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('loads local context and proposes capture through the action boundary', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([RECORD]))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response(ACTION))
    const proposed = vi.fn()
    const { result } = renderHook(() => useContextInspector(true, proposed))
    await waitFor(() => expect(result.current.records).toHaveLength(1))
    await act(async () => { await result.current.capture({ kind: 'note', text: 'Keep the plan concise.' }) })
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/cortex/context/captures'), expect.objectContaining({ method: 'POST' }))
    expect(proposed).toHaveBeenCalledWith(expect.objectContaining({ action_id: 'action-1' }))
  })

  it('prepares retrieval only from an explicit operator action', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([RECORD]))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response({ ...STATUS, mode: 'semantic', state: 'ready', embedding_items: 1, pending_items: 0 }))
    const { result } = renderHook(() => useContextInspector(true, vi.fn()))
    await waitFor(() => expect(result.current.retrieval?.state).toBe('unprepared'))
    await act(async () => { await result.current.prepare() })
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/cortex/retrieval/prepare'), { method: 'POST' })
    expect(result.current.retrieval?.state).toBe('ready')
  })

  it('toggles the selected context record and clears it when its category no longer matches', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([RECORD]))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response(DETAIL))
    const { result } = renderHook(() => useContextInspector(true, vi.fn()))
    await waitFor(() => expect(result.current.records).toHaveLength(1))

    await act(async () => { await result.current.selectRecord(RECORD.id) })
    expect(result.current.selectedRecordId).toBe(RECORD.id)
    await act(async () => { await result.current.selectRecord(RECORD.id) })
    expect(result.current.selectedRecordId).toBeNull()

    await act(async () => { await result.current.selectRecord(RECORD.id) })
    await act(async () => { result.current.setFilters((current) => ({ ...current, kind: 'goal' })) })
    await waitFor(() => expect(result.current.selectedRecordId).toBeNull())
    expect(result.current.detail).toBeNull()
  })

  it('keeps the latest selected record when an earlier detail request finishes late', async () => {
    let resolveFirst: ((value: Response) => void) | undefined
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([RECORD]))
      .mockResolvedValueOnce(response(STATUS))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(response({ ...DETAIL, id: 'record-2', text: 'Second record' }))
    const { result } = renderHook(() => useContextInspector(true, vi.fn()))
    await waitFor(() => expect(result.current.records).toHaveLength(1))
    let firstRequest: Promise<void>
    act(() => { firstRequest = result.current.selectRecord(RECORD.id) })
    await act(async () => { await result.current.selectRecord('record-2') })
    await waitFor(() => expect(result.current.detail?.id).toBe('record-2'))
    await act(async () => { resolveFirst?.(response(DETAIL)); await firstRequest })
    expect(result.current.detail?.id).toBe('record-2')
  })
})
