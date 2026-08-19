import { useCallback, useEffect, useMemo, useState, type SetStateAction } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { ActionRecord } from '../types/actions'
import type {
  ContextAction, ContextCaptureInput, ContextEntity, ContextKind, ContextRecord,
  ContextRecordDetail, ContextStatus, RetrievalStatus,
} from '../types/context'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

async function bodyOrError(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => null) as unknown
  if (response.ok) return body
  if (isRecord(body) && typeof body.detail === 'string') throw new Error(body.detail)
  throw new Error('Context request failed. Try again.')
}

function asAction(value: unknown): ActionRecord | null {
  if (!isRecord(value) || !isRecord(value.proposal)) return null
  const proposal = value.proposal
  if (typeof value.action_id !== 'string' || typeof value.status !== 'string' || typeof value.version !== 'number' || typeof value.updated_at !== 'string' || typeof proposal.capability_name !== 'string') return null
  return value as unknown as ActionRecord
}

function asRetrievalStatus(value: unknown): RetrievalStatus | null {
  if (!isRecord(value)) return null
  return typeof value.enabled === 'boolean' && typeof value.mode === 'string' && typeof value.state === 'string' && typeof value.indexed_items === 'number' && typeof value.embedding_items === 'number' && typeof value.pending_items === 'number'
    ? value as unknown as RetrievalStatus : null
}

function asRecords(value: unknown): ContextRecord[] | null {
  return Array.isArray(value) && value.every(isRecord) ? value as unknown as ContextRecord[] : null
}

function asDetail(value: unknown): ContextRecordDetail | null {
  return isRecord(value) && Array.isArray(value.sources) && Array.isArray(value.related_records) ? value as unknown as ContextRecordDetail : null
}

export interface ContextFilters {
  query: string
  kind: ContextKind | ''
  statuses: ContextStatus[]
}

function matchesContextCategory(record: ContextRecord, filters: ContextFilters): boolean {
  return !filters.kind || record.kind === filters.kind
}

export function useContextInspector(enabled: boolean, onActionProposed: (action: ActionRecord) => void) {
  const [records, setRecords] = useState<ContextRecord[]>([])
  const [detail, setDetail] = useState<ContextRecordDetail | null>(null)
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null)
  const [filters, setFilters] = useState<ContextFilters>({ query: '', kind: '', statuses: ['active', 'conflicting'] })
  const [isLoading, setIsLoading] = useState(false)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retrieval, setRetrieval] = useState<RetrievalStatus | null>(null)
  const [isPreparing, setIsPreparing] = useState(false)
  const [lastCreatedRecordId, setLastCreatedRecordId] = useState<string | null>(null)
  const [entities, setEntities] = useState<ContextEntity[]>([])

  const updateFilters = useCallback((update: SetStateAction<ContextFilters>): void => {
    setFilters(update)
  }, [])

  useEffect(() => {
    const selected = detail ?? records.find((record) => record.id === selectedRecordId)
    if (selected && !matchesContextCategory(selected, filters)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Clear detail when its record is excluded by the active kind category.
      setSelectedRecordId(null)
      setDetail(null)
    }
  }, [detail, filters, records, selectedRecordId])

  const refresh = useCallback(async (): Promise<void> => {
    if (!enabled) return
    setIsLoading(true)
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (filters.query.trim()) params.set('q', filters.query.trim())
      if (filters.kind) params.set('kind', filters.kind)
      filters.statuses.forEach((status) => params.append('status', status))
      const [recordsBody, statusBody] = await Promise.all([
        fetch(`${API_ENDPOINTS.cortexContext}?${params}`).then(bodyOrError),
        fetch(API_ENDPOINTS.cortexRetrievalStatus).then(bodyOrError),
      ])
      const nextRecords = asRecords(recordsBody)
      const nextStatus = asRetrievalStatus(statusBody)
      if (!nextRecords || !nextStatus) throw new Error('Context data is unavailable.')
      setRecords(nextRecords)
      setRetrieval(nextStatus)
      setError(null)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Context data could not be reached.')
    } finally {
      setIsLoading(false)
    }
  }, [enabled, filters])

  const selectRecord = useCallback(async (recordId: string | null): Promise<void> => {
    if (recordId && recordId === selectedRecordId) {
      setSelectedRecordId(null)
      setDetail(null)
      return
    }
    setSelectedRecordId(recordId)
    setDetail(null)
    if (!recordId || !enabled) return
    setIsDetailLoading(true)
    try {
      const parsed = asDetail(await fetch(API_ENDPOINTS.cortexContextRecord(recordId)).then(bodyOrError))
      if (!parsed) throw new Error('Context detail is unavailable.')
      setDetail(parsed)
      setError(null)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Context detail could not be reached.')
    } finally {
      setIsDetailLoading(false)
    }
  }, [enabled, selectedRecordId])

  useEffect(() => {
    queueMicrotask(() => void refresh())
  }, [refresh])

  const propose = useCallback(async (url: string, payload: ContextCaptureInput | ContextAction): Promise<boolean> => {
    try {
      const parsed = asAction(await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(bodyOrError))
      if (!parsed) throw new Error('Context action could not be proposed.')
      onActionProposed(parsed)
      setError(null)
      return true
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Context action could not be reached.')
      return false
    }
  }, [onActionProposed])

  const prepare = useCallback(async (): Promise<void> => {
    if (isPreparing) return
    setIsPreparing(true)
    try {
      const parsed = asRetrievalStatus(await fetch(API_ENDPOINTS.cortexRetrievalPrepare, { method: 'POST' }).then(bodyOrError))
      if (!parsed) throw new Error('Retrieval status is unavailable.')
      setRetrieval(parsed)
      setError(null)
    } catch (prepareError) {
      setError(prepareError instanceof Error ? prepareError.message : 'Retrieval preparation failed.')
    } finally {
      setIsPreparing(false)
    }
  }, [isPreparing])

  const rememberVerifiedRecord = useCallback((recordId: string | null): void => {
    if (recordId) setLastCreatedRecordId(recordId)
    void refresh()
  }, [refresh])

  const searchEntities = useCallback(async (query = ''): Promise<void> => {
    try {
      const params = new URLSearchParams({ limit: '50' })
      if (query.trim()) params.set('q', query.trim())
      const body = await fetch(`${API_ENDPOINTS.cortexContextEntities}?${params}`).then(bodyOrError)
      if (!Array.isArray(body) || !body.every(isRecord)) throw new Error('Entity data is unavailable.')
      setEntities(body as unknown as ContextEntity[])
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Entity data could not be reached.')
    }
  }, [])

  return useMemo(() => ({
    records, detail, selectedRecordId, filters, setFilters: updateFilters, isLoading, isDetailLoading, error,
    retrieval, isPreparing, lastCreatedRecordId, entities, refresh, selectRecord, prepare, searchEntities,
    capture: (payload: ContextCaptureInput) => propose(API_ENDPOINTS.cortexContextCapture, payload),
    reconcile: (payload: ContextAction) => propose(API_ENDPOINTS.cortexContextActions, payload),
    rememberVerifiedRecord,
  }), [detail, entities, error, filters, isDetailLoading, isLoading, isPreparing, lastCreatedRecordId, prepare, propose, records, refresh, retrieval, selectRecord, selectedRecordId, rememberVerifiedRecord, searchEntities, updateFilters])
}
