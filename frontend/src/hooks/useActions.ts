import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type {
  ActionDetail,
  ActionEvent,
  ActionMutation,
  ActionProposal,
  ActionRecord,
  ActionRisk,
  ActionStatus,
} from '../types/actions'

const POLL_INTERVAL_MS = 5_000
const ACTION_STATUSES: readonly ActionStatus[] = [
  'proposed', 'approved', 'executing', 'verifying', 'verified', 'rejected',
  'expired', 'execution_failed', 'verification_failed', 'outcome_unknown',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isActionStatus(value: unknown): value is ActionStatus {
  return typeof value === 'string' && ACTION_STATUSES.includes(value as ActionStatus)
}

function parseProposal(value: unknown): ActionProposal | null {
  if (!isRecord(value) || !isRecord(value.arguments)) return null
  if (
    typeof value.agent_key !== 'string' ||
    typeof value.capability_name !== 'string' ||
    typeof value.target !== 'string' ||
    (value.risk !== 'write' && value.risk !== 'destructive') ||
    typeof value.summary !== 'string' ||
    typeof value.proposed_at !== 'string' ||
    typeof value.expires_at !== 'string' ||
    typeof value.proposal_hash !== 'string'
  ) return null
  return {
    agent_key: value.agent_key,
    capability_name: value.capability_name,
    arguments: value.arguments,
    target: value.target,
    risk: value.risk as ActionRisk,
    summary: value.summary,
    proposed_at: value.proposed_at,
    expires_at: value.expires_at,
    proposal_hash: value.proposal_hash,
  }
}

function parseActionRecord(value: unknown): ActionRecord | null {
  if (!isRecord(value)) return null
  const proposal = parseProposal(value.proposal)
  if (
    !proposal ||
    typeof value.action_id !== 'string' ||
    !isActionStatus(value.status) ||
    typeof value.version !== 'number' ||
    !Number.isInteger(value.version) ||
    value.version < 0 ||
    typeof value.updated_at !== 'string'
  ) return null
  return {
    action_id: value.action_id,
    proposal,
    status: value.status,
    version: value.version,
    updated_at: value.updated_at,
  }
}

function parseActionEvent(value: unknown): ActionEvent | null {
  if (!isRecord(value) || !isRecord(value.evidence)) return null
  if (
    typeof value.action_id !== 'string' ||
    typeof value.sequence !== 'number' ||
    !Number.isInteger(value.sequence) ||
    (value.from_status !== null && !isActionStatus(value.from_status)) ||
    !isActionStatus(value.to_status) ||
    typeof value.occurred_at !== 'string' ||
    typeof value.actor !== 'string' ||
    typeof value.result_code !== 'string'
  ) return null
  return {
    action_id: value.action_id,
    sequence: value.sequence,
    from_status: value.from_status as ActionStatus | null,
    to_status: value.to_status,
    occurred_at: value.occurred_at,
    actor: value.actor,
    result_code: value.result_code,
    evidence: value.evidence,
  }
}

function parseActions(value: unknown): ActionRecord[] | null {
  if (!Array.isArray(value)) return null
  const parsed = value.map(parseActionRecord)
  return parsed.every((item): item is ActionRecord => item !== null) ? parsed : null
}

function parseActionDetail(value: unknown): ActionDetail | null {
  const action = parseActionRecord(value)
  if (!action || !isRecord(value) || !Array.isArray(value.events)) return null
  const events = value.events.map(parseActionEvent)
  if (!events.every((item): item is ActionEvent => item !== null)) return null
  return { ...action, events }
}

async function errorMessage(response: Response): Promise<string> {
  if (response.status === 404) return 'This action is no longer available.'
  if (response.status === 503) return 'Action controls are unavailable.'
  try {
    const body: unknown = await response.json()
    if (isRecord(body) && typeof body.detail === 'string') return body.detail
  } catch {
    // Keep the stable fallback below.
  }
  return 'Action request failed. Try again.'
}

export interface UseActionsResult {
  actions: ActionRecord[]
  pendingCount: number
  isLoading: boolean
  error: string | null
  selectedActionId: string | null
  detail: ActionDetail | null
  isDetailLoading: boolean
  mutation: ActionMutation | null
  setSelectedActionId: (actionId: string | null) => void
  refresh: () => Promise<void>
  resolve: (mutation: ActionMutation) => Promise<void>
}

export function useActions(enabled: boolean): UseActionsResult {
  const [actions, setActions] = useState<ActionRecord[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ActionDetail | null>(null)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [detailReloadToken, setDetailReloadToken] = useState(0)
  const [mutation, setMutation] = useState<ActionMutation | null>(null)
  const listControllerRef = useRef<AbortController | null>(null)
  const detailControllerRef = useRef<AbortController | null>(null)
  const detailRef = useRef<ActionDetail | null>(null)

  useEffect(() => {
    detailRef.current = detail
  }, [detail])

  const refresh = useCallback(async (): Promise<void> => {
    if (!enabled) return
    listControllerRef.current?.abort()
    const controller = new AbortController()
    listControllerRef.current = controller
    setIsLoading(true)
    try {
      const pendingUrl = `${API_ENDPOINTS.actions}?status=proposed&limit=50`
      const [actionsResponse, pendingResponse] = await Promise.all([
        fetch(`${API_ENDPOINTS.actions}?limit=50`, { signal: controller.signal }),
        fetch(pendingUrl, { signal: controller.signal }),
      ])
      if (controller.signal.aborted) return
      if (!actionsResponse.ok || !pendingResponse.ok) {
        setError(await errorMessage(!actionsResponse.ok ? actionsResponse : pendingResponse))
        return
      }
      const [actionsBody, pendingBody]: [unknown, unknown] = await Promise.all([
        actionsResponse.json(), pendingResponse.json(),
      ])
      const parsedActions = parseActions(actionsBody)
      const parsedPending = parseActions(pendingBody)
      if (!parsedActions || !parsedPending) {
        setError('Action data is unavailable.')
        return
      }
      setActions(parsedActions)
      setPendingCount(parsedPending.length)
      setError(null)
      const expandedDetail = detailRef.current
      const currentRecord = expandedDetail
        ? parsedActions.find((action) => action.action_id === expandedDetail.action_id)
        : null
      if (currentRecord && currentRecord.version !== expandedDetail?.version) {
        setDetailReloadToken((current) => current + 1)
      }
      setSelectedActionId((current) => current && !parsedActions.some((action) => action.action_id === current) ? null : current)
    } catch (fetchError) {
      if (!(fetchError instanceof DOMException && fetchError.name === 'AbortError')) {
        setError('Action controls could not be reached.')
      }
    } finally {
      if (!controller.signal.aborted) setIsLoading(false)
    }
  }, [enabled])

  const loadDetail = useCallback(async (actionId: string): Promise<void> => {
    if (!enabled) return
    detailControllerRef.current?.abort()
    const controller = new AbortController()
    detailControllerRef.current = controller
    setIsDetailLoading(true)
    try {
      const response = await fetch(API_ENDPOINTS.action(actionId), { signal: controller.signal })
      if (controller.signal.aborted) return
      if (!response.ok) {
        setDetail(null)
        setError(await errorMessage(response))
        if (response.status === 404) setSelectedActionId(null)
        return
      }
      const parsed = parseActionDetail(await response.json())
      if (!parsed) {
        setDetail(null)
        setError('Action details are unavailable.')
        return
      }
      setDetail(parsed)
      setError(null)
    } catch (fetchError) {
      if (!(fetchError instanceof DOMException && fetchError.name === 'AbortError')) {
        setError('Action details could not be reached.')
      }
    } finally {
      if (!controller.signal.aborted) setIsDetailLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled || !selectedActionId) return
    queueMicrotask(() => void loadDetail(selectedActionId))
  }, [enabled, selectedActionId, loadDetail, detailReloadToken])

  useEffect(() => {
    if (!enabled) {
      listControllerRef.current?.abort()
      detailControllerRef.current?.abort()
      return
    }
    let intervalId: number | null = null
    const startPolling = (): void => {
      if (document.hidden || intervalId !== null) return
      void refresh()
      intervalId = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    }
    const stopPolling = (): void => {
      if (intervalId !== null) {
        window.clearInterval(intervalId)
        intervalId = null
      }
    }
    const onVisibilityChange = (): void => {
      if (document.hidden) stopPolling()
      else startPolling()
    }
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', onVisibilityChange)
      listControllerRef.current?.abort()
      detailControllerRef.current?.abort()
    }
  }, [enabled, refresh])

  const resolve = useCallback(async (requested: ActionMutation): Promise<void> => {
    if (!enabled || mutation || !detail) return
    const endpoint = requested === 'approve'
      ? API_ENDPOINTS.actionApprove(detail.action_id)
      : requested === 'reject'
        ? API_ENDPOINTS.actionReject(detail.action_id)
        : API_ENDPOINTS.actionVerify(detail.action_id)
    setMutation(requested)
    setError(null)
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: detail.version }),
      })
      if (response.status === 409) {
        setError('This action changed. Its latest state is shown.')
      } else if (!response.ok) {
        setError(await errorMessage(response))
      }
      await refresh()
      await loadDetail(detail.action_id)
    } catch {
      setError('Action request could not be reached.')
    } finally {
      setMutation(null)
    }
  }, [detail, enabled, loadDetail, mutation, refresh])

  const selectAction = useCallback((actionId: string | null): void => {
    detailControllerRef.current?.abort()
    setSelectedActionId(actionId)
    setDetail(null)
    setIsDetailLoading(false)
  }, [])

  return {
    actions: enabled ? actions : [],
    pendingCount: enabled ? pendingCount : 0,
    isLoading: enabled && isLoading,
    error: enabled ? error : null,
    selectedActionId: enabled ? selectedActionId : null,
    detail: enabled ? detail : null,
    isDetailLoading: enabled && isDetailLoading,
    mutation: enabled ? mutation : null,
    setSelectedActionId: selectAction, refresh, resolve,
  }
}
