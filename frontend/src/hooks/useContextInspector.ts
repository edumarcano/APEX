import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { ActionRecord } from '../types/actions'
import type { ContextAction, ContextCaptureInput, ContextEntity, ContextKind, ContextRecord, ContextRecordDetail, ContextReview, ContextReviewDecision, ContextSaveInput, ContextSaveResult, ContextStatus, RetrievalStatus } from '../types/context'

function isRecord(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value) }
class ContextRequestError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
async function bodyOrError(response: Response): Promise<unknown> { const body = await response.json().catch(() => null) as unknown; if (response.ok) return body; throw new ContextRequestError(isRecord(body) && typeof body.detail === 'string' ? body.detail : 'Context request failed. Try again.', response.status) }
function asStatus(value: unknown): RetrievalStatus | null {
  return isRecord(value)
    && typeof value.enabled === 'boolean'
    && typeof value.mode === 'string'
    && typeof value.state === 'string'
    && typeof value.indexed_items === 'number'
    && typeof value.pending_items === 'number'
    ? value as unknown as RetrievalStatus
    : null
}
function asDetail(value: unknown): ContextRecordDetail | null { return isRecord(value) && Array.isArray(value.sources) && Array.isArray(value.related_records) && Array.isArray(value.history) && Array.isArray(value.pending_review_ids) ? value as unknown as ContextRecordDetail : null }
function asReview(value: unknown): ContextReview | null { return isRecord(value) && typeof value.id === 'string' && isRecord(value.proposal) && isRecord(value.evidence) && isRecord(value.expected_revisions) && Array.isArray(value.reason_codes) ? value as unknown as ContextReview : null }
function reviewRecordIds(review: ContextReview): string[] { return Object.keys(review.expected_revisions).filter((key) => !key.includes(':')) }
export interface ContextFilters { query: string; kind: ContextKind | ''; statuses: ContextStatus[] }
export interface ContextReviewFilters { decisions: ContextReviewDecision[] }

export function useContextInspector(enabled: boolean, onActionProposed: (action: ActionRecord) => void) {
  const [records, setRecords] = useState<ContextRecord[]>([])
  const [detail, setDetail] = useState<ContextRecordDetail | null>(null)
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null)
  const [filters, setFilters] = useState<ContextFilters>({ query: '', kind: '', statuses: ['active', 'conflicting'] })
  const [retrieval, setRetrieval] = useState<RetrievalStatus | null>(null)
  const [isLoading, setIsLoading] = useState(false); const [isDetailLoading, setIsDetailLoading] = useState(false); const [isPreparing, setIsPreparing] = useState(false)
  const [error, setError] = useState<string | null>(null); const [entities, setEntities] = useState<ContextEntity[]>([]); const [lastCreatedRecordId, setLastCreatedRecordId] = useState<string | null>(null)
  const [reviews, setReviews] = useState<ContextReview[]>([]); const [pendingReviewCount, setPendingReviewCount] = useState(0); const [reviewFilters, setReviewFilters] = useState<ContextReviewFilters>({ decisions: ['pending'] })
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null); const [reviewDetail, setReviewDetail] = useState<ContextReview | null>(null); const [reviewRecords, setReviewRecords] = useState<ContextRecordDetail[]>([]); const [isReviewLoading, setIsReviewLoading] = useState(false); const [reviewMutation, setReviewMutation] = useState<string | null>(null); const [reviewRefreshRequired, setReviewRefreshRequired] = useState(false)
  const recordRequest = useRef(0); const reviewRequest = useRef(0)
  const updateFilters = useCallback((update: SetStateAction<ContextFilters>) => setFilters(update), [])
  useEffect(() => { const selected = detail ?? records.find((record) => record.id === selectedRecordId); if (selected && filters.kind && selected.kind !== filters.kind) { queueMicrotask(() => { setSelectedRecordId(null); setDetail(null) }) } }, [detail, filters.kind, records, selectedRecordId])
  const refresh = useCallback(async (): Promise<void> => {
    if (!enabled) return; setIsLoading(true)
    try {
      const recordParams = new URLSearchParams({ limit: '100' }); if (filters.query.trim()) recordParams.set('q', filters.query.trim()); if (filters.kind) recordParams.set('kind', filters.kind); filters.statuses.forEach((status) => recordParams.append('status', status))
      const reviewParams = new URLSearchParams({ limit: '100' }); reviewFilters.decisions.forEach((decision) => reviewParams.append('decision', decision))
      const [recordsBody, statusBody, reviewsBody, pendingBody] = await Promise.all([
        fetch(`${API_ENDPOINTS.cortexContext}?${recordParams}`).then(bodyOrError),
        fetch(API_ENDPOINTS.cortexRetrievalStatus).then(bodyOrError),
        fetch(`${API_ENDPOINTS.cortexContextReviews}?${reviewParams}`).then(bodyOrError),
        fetch(`${API_ENDPOINTS.cortexContextReviews}?limit=100&decision=pending`).then(bodyOrError),
      ])
      if (!Array.isArray(recordsBody) || !recordsBody.every(isRecord) || !asStatus(statusBody) || !Array.isArray(reviewsBody) || !reviewsBody.every((item) => asReview(item))) throw new Error('Context data is unavailable.')
      if (!Array.isArray(pendingBody) || !pendingBody.every((item) => asReview(item))) throw new Error('Context reviews are unavailable.')
      setRecords(recordsBody as unknown as ContextRecord[]); setRetrieval(asStatus(statusBody)); setReviews(reviewsBody as ContextReview[]); setPendingReviewCount(pendingBody.length); setError(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Context data could not be reached.') } finally { setIsLoading(false) }
  }, [enabled, filters, reviewFilters])
  const selectRecord = useCallback(async (recordId: string | null, force = false): Promise<void> => { const request = ++recordRequest.current; if (!force && recordId === selectedRecordId) { setSelectedRecordId(null); setDetail(null); return }; setSelectedRecordId(recordId); setDetail(null); if (!recordId || !enabled) return; setIsDetailLoading(true); try { const parsed = asDetail(await fetch(API_ENDPOINTS.cortexContextRecord(recordId)).then(bodyOrError)); if (!parsed) throw new Error('Context detail is unavailable.'); if (request === recordRequest.current) { setDetail(parsed); setError(null) } } catch (cause) { if (request === recordRequest.current) setError(cause instanceof Error ? cause.message : 'Context detail could not be reached.') } finally { if (request === recordRequest.current) setIsDetailLoading(false) } }, [enabled, selectedRecordId])
  const selectReview = useCallback(async (reviewId: string | null): Promise<void> => { const request = ++reviewRequest.current; setSelectedReviewId(reviewId); setReviewDetail(null); setReviewRecords([]); setReviewRefreshRequired(false); if (!reviewId || !enabled) return; setIsReviewLoading(true); try { const review = asReview(await fetch(API_ENDPOINTS.cortexContextReview(reviewId)).then(bodyOrError)); if (!review) throw new Error('Context review is unavailable.'); const details = await Promise.all(reviewRecordIds(review).map(async (id) => asDetail(await fetch(API_ENDPOINTS.cortexContextRecord(id)).then(bodyOrError)))); if (request !== reviewRequest.current) return; setReviewDetail(review); setReviewRecords(details.filter((item): item is ContextRecordDetail => item !== null)); setError(null) } catch (cause) { if (request === reviewRequest.current) setError(cause instanceof Error ? cause.message : 'Context review could not be reached.') } finally { if (request === reviewRequest.current) setIsReviewLoading(false) } }, [enabled])
  useEffect(() => { queueMicrotask(() => void refresh()) }, [refresh])
  const postAction = useCallback(async (url: string, payload: ContextCaptureInput | ContextAction): Promise<boolean> => { try { const value = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(bodyOrError); if (!isRecord(value) || !isRecord(value.proposal)) throw new Error('Context action could not be proposed.'); onActionProposed(value as unknown as ActionRecord); setError(null); return true } catch (cause) { setError(cause instanceof Error ? cause.message : 'Context action could not be reached.'); return false } }, [onActionProposed])
  const save = useCallback(async (payload: ContextSaveInput): Promise<ContextSaveResult | null> => { try { const value = await fetch(API_ENDPOINTS.cortexContextSave, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, text: payload.text.trim() }) }).then(bodyOrError); if (!isRecord(value) || (value.outcome !== 'saved' && value.outcome !== 'review_required')) throw new Error('Context save is unavailable.'); const result = value as unknown as ContextSaveResult; if (result.record_id) setLastCreatedRecordId(result.record_id); await refresh(); return result } catch (cause) { setError(cause instanceof Error ? cause.message : 'Context save could not be reached.'); return null } }, [refresh])
  const decideReview = useCallback(async (decision: 'accept' | 'reject' | 'refresh'): Promise<boolean> => { if (!reviewDetail || reviewMutation) return false; setReviewMutation(decision); try { const next = asReview(await fetch(API_ENDPOINTS.cortexContextReviewDecision(reviewDetail.id, decision), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revisions: reviewDetail.expected_revisions }) }).then(bodyOrError)); if (!next) throw new Error('Context review is unavailable.'); setError(null); setReviewRefreshRequired(false); await refresh(); await selectReview(next.id); return true } catch (cause) { if (cause instanceof ContextRequestError && cause.status === 409) { await selectReview(reviewDetail.id); setReviewRefreshRequired(true) } setError(cause instanceof Error ? cause.message : 'Context review could not be updated.'); return false } finally { setReviewMutation(null) } }, [refresh, reviewDetail, reviewMutation, selectReview])
  const prepare = useCallback(async () => { if (isPreparing) return; setIsPreparing(true); try { const next = asStatus(await fetch(API_ENDPOINTS.cortexRetrievalPrepare, { method: 'POST' }).then(bodyOrError)); if (!next) throw new Error('Retrieval status is unavailable.'); setRetrieval(next); setError(null) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Retrieval preparation failed.') } finally { setIsPreparing(false) } }, [isPreparing])
  const searchEntities = useCallback(async () => { try { const body = await fetch(`${API_ENDPOINTS.cortexContextEntities}?limit=50`).then(bodyOrError); if (!Array.isArray(body)) throw new Error('Entity data is unavailable.'); setEntities(body as ContextEntity[]) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Entity data could not be reached.') } }, [])
  const rememberVerifiedRecord = useCallback((id: string | null) => { if (id) setLastCreatedRecordId(id); void refresh() }, [refresh])
  return useMemo(() => ({ records, detail, selectedRecordId, filters, setFilters: updateFilters, retrieval, isLoading, isDetailLoading, isPreparing, error, entities, lastCreatedRecordId, reviews, pendingReviewCount, reviewFilters, setReviewFilters, selectedReviewId, reviewDetail, reviewRecords, isReviewLoading, reviewMutation, reviewRefreshRequired, refresh, selectRecord, selectReview, decideReview, prepare, searchEntities, save, capture: (value: ContextCaptureInput) => postAction(API_ENDPOINTS.cortexContextCapture, value), reconcile: (value: ContextAction) => postAction(API_ENDPOINTS.cortexContextActions, value), rememberVerifiedRecord }), [detail, entities, error, filters, isDetailLoading, isLoading, isPreparing, isReviewLoading, lastCreatedRecordId, pendingReviewCount, prepare, records, refresh, retrieval, reviewDetail, reviewFilters, reviewMutation, reviewRecords, reviewRefreshRequired, reviews, save, searchEntities, selectRecord, selectReview, selectedRecordId, selectedReviewId, decideReview, postAction, rememberVerifiedRecord, updateFilters])
}
