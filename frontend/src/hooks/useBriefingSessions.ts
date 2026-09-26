import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type {
  BriefingEvidence,
  BriefingProfileId,
  BriefingProfileSummary,
  BriefingSessionDetail,
  BriefingSessionSummary,
} from '../types/briefings'

type BriefingGenerationOptions = {
  modelId: string
  reasoning?: string | null
  contextWindow?: number | null
  localReasoningMode?: 'none' | 'focused' | null
}

type HookState = {
  sessions: BriefingSessionSummary[]
  profiles: BriefingProfileSummary[]
  selectedSessionId: string | null
  activeSession: BriefingSessionDetail | null
  evidenceById: Record<string, BriefingEvidence>
  evidenceLoadingIds: string[]
  evidenceErrors: Record<string, string>
  isLoadingSessions: boolean
  isLoadingSession: boolean
  isGenerating: boolean
  error: string | null
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as unknown
    throw new Error(errorMessage(body, 'APEX request failed (' + response.status + ')'))
  }
  return response.json() as Promise<T>
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'cancelling'])

function updateSummary(
  sessions: BriefingSessionSummary[],
  next: BriefingSessionSummary,
): BriefingSessionSummary[] {
  return [next, ...sessions.filter((session) => session.id !== next.id)]
}

export type UseBriefingSessionsResult = HookState & {
  hasActiveSession: boolean
  refreshSessions: () => Promise<void>
  generate: (profileId: BriefingProfileId, options: BriefingGenerationOptions) => Promise<BriefingSessionSummary>
  openSession: (sessionId: string) => Promise<BriefingSessionDetail>
  loadEvidence: (sessionId: string, evidenceId: string) => Promise<void>
  markPresented: (sessionId: string) => Promise<void>
  cancelSession: (sessionId: string) => Promise<void>
}

export function useBriefingSessions(): UseBriefingSessionsResult {
  const [sessions, setSessions] = useState<BriefingSessionSummary[]>([])
  const [profiles, setProfiles] = useState<BriefingProfileSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [activeSession, setActiveSession] = useState<BriefingSessionDetail | null>(null)
  const [evidenceById, setEvidenceById] = useState<Record<string, BriefingEvidence>>({})
  const [evidenceLoadingIds, setEvidenceLoadingIds] = useState<string[]>([])
  const [evidenceErrors, setEvidenceErrors] = useState<Record<string, string>>({})
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadSequence = useRef(0)
  const generatingRef = useRef(false)
  const selectedSessionRef = useRef<string | null>(null)
  const evidenceLoadedRef = useRef(new Set<string>())
  const evidenceLoadingRef = useRef(new Set<string>())
  const idempotencyRef = useRef<{ fingerprint: string; key: string } | null>(null)
  selectedSessionRef.current = selectedSessionId

  const refreshSessions = useCallback(async (): Promise<void> => {
    setIsLoadingSessions(true)
    try {
      const next = await requestJson<BriefingSessionSummary[]>(API_ENDPOINTS.briefingSessions({ limit: 50 }))
      setSessions((current) => {
        const listed = Array.isArray(next) ? next : []
        const listedIds = new Set(listed.map((session) => session.id))
        const admitted = current.filter((session) => ACTIVE_STATUSES.has(session.run_status) && !listedIds.has(session.id))
        return [...admitted, ...listed]
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Saved Daily sessions are unavailable.')
    } finally {
      setIsLoadingSessions(false)
    }
  }, [])

  const openSession = useCallback(async (sessionId: string): Promise<BriefingSessionDetail> => {
    const sequence = ++loadSequence.current
    if (selectedSessionRef.current !== sessionId) {
      evidenceLoadedRef.current.clear()
      setActiveSession(null)
      setEvidenceById({})
      setEvidenceLoadingIds([])
      setEvidenceErrors({})
    }
    selectedSessionRef.current = sessionId
    setSelectedSessionId(sessionId)
    setIsLoadingSession(true)
    setError(null)
    try {
      const detail = await requestJson<BriefingSessionDetail>(API_ENDPOINTS.briefingSession(sessionId))
      if (loadSequence.current === sequence) {
        setActiveSession(detail)
        setSessions((current) => updateSummary(current, {
          id: detail.id,
          profile_id: detail.configuration.profile.id,
          model_id: detail.configuration.model.model_id,
          conversation_id: detail.conversation_id,
          run_id: detail.run_id,
          run_status: detail.run_status,
          created_at: detail.created_at,
          presented_at: detail.presented_at,
        }))
      }
      return detail
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Daily session could not be loaded.'
      if (loadSequence.current === sequence) setError(message)
      throw cause
    } finally {
      if (loadSequence.current === sequence) setIsLoadingSession(false)
    }
  }, [])

  const loadEvidence = useCallback(async (sessionId: string, evidenceId: string): Promise<void> => {
    if (evidenceLoadedRef.current.has(evidenceId) || evidenceLoadingRef.current.has(evidenceId)) return
    evidenceLoadingRef.current.add(evidenceId)
    setEvidenceLoadingIds((current) => current.includes(evidenceId) ? current : [...current, evidenceId])
    setEvidenceErrors((current) => {
      const next = { ...current }
      delete next[evidenceId]
      return next
    })
    try {
      const evidence = await requestJson<BriefingEvidence>(API_ENDPOINTS.briefingSessionEvidence(sessionId, evidenceId))
      evidenceLoadedRef.current.add(evidenceId)
      setEvidenceById((current) => ({ ...current, [evidence.id]: evidence }))
    } catch (cause) {
      setEvidenceErrors((current) => ({
        ...current,
        [evidenceId]: cause instanceof Error ? cause.message : 'Evidence could not be loaded.',
      }))
    } finally {
      evidenceLoadingRef.current.delete(evidenceId)
      setEvidenceLoadingIds((current) => current.filter((id) => id !== evidenceId))
    }
  }, [])

  const generate = useCallback(async (profileId: BriefingProfileId, options: BriefingGenerationOptions): Promise<BriefingSessionSummary> => {
    if (generatingRef.current || sessions.some((session) => ACTIVE_STATUSES.has(session.run_status))) {
      throw new Error('A Daily briefing is already running.')
    }
    generatingRef.current = true
    setIsGenerating(true)
    setError(null)
    const fingerprint = JSON.stringify({ profileId, options })
    if (idempotencyRef.current?.fingerprint !== fingerprint) {
      idempotencyRef.current = { fingerprint, key: crypto.randomUUID() }
    }
    try {
      const body = {
        idempotency_key: idempotencyRef.current.key,
        profile_id: profileId,
        model_id: options.modelId,
        ...(options.reasoning ? { reasoning: options.reasoning } : {}),
        ...(options.contextWindow ? { context_window: options.contextWindow } : {}),
        ...(options.localReasoningMode ? { local_reasoning_mode: options.localReasoningMode } : {}),
      }
      const summary = await requestJson<BriefingSessionSummary>(API_ENDPOINTS.briefingSessions(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      idempotencyRef.current = null
      setSessions((current) => updateSummary(current, summary))
      void openSession(summary.id).catch(() => undefined)
      void refreshSessions()
      return summary
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Daily briefing could not be started.'
      setError(message)
      throw cause
    } finally {
      generatingRef.current = false
      setIsGenerating(false)
    }
  }, [openSession, refreshSessions, sessions])

  const markPresented = useCallback(async (sessionId: string): Promise<void> => {
    const detail = await requestJson<BriefingSessionDetail>(API_ENDPOINTS.briefingSessionPresented(sessionId), { method: 'POST' })
    setActiveSession((current) => current?.id === sessionId ? { ...current, presented_at: detail.presented_at } : current)
    setSessions((current) => current.map((session) => session.id === sessionId
      ? { ...session, presented_at: detail.presented_at }
      : session))
  }, [])

  const cancelSession = useCallback(async (sessionId: string): Promise<void> => {
    const target = sessions.find((session) => session.id === sessionId)
    if (!target) return
    await requestJson(API_ENDPOINTS.cortexRunCancel(target.run_id), { method: 'POST' })
  }, [sessions])

  useEffect(() => {
    void refreshSessions()
  }, [refreshSessions])

  useEffect(() => {
    let cancelled = false
    requestJson<BriefingProfileSummary[]>(API_ENDPOINTS.briefingProfiles)
      .then((next) => { if (!cancelled && Array.isArray(next)) setProfiles(next) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const session = activeSession
    if (!session || !ACTIVE_STATUSES.has(session.run_status)) return undefined
    const timeout = window.setTimeout(() => { void openSession(session.id).catch(() => undefined) }, 900)
    return () => window.clearTimeout(timeout)
  }, [activeSession, openSession])

  return {
    sessions,
    profiles,
    selectedSessionId,
    activeSession,
    evidenceById,
    evidenceLoadingIds,
    evidenceErrors,
    isLoadingSessions,
    isLoadingSession,
    isGenerating,
    error,
    hasActiveSession: isGenerating || sessions.some((session) => ACTIVE_STATUSES.has(session.run_status)),
    refreshSessions,
    generate,
    openSession,
    loadEvidence,
    markPresented,
    cancelSession,
  }
}
