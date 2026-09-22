import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { ContextReview } from '../types/context'
import type {
  ActivityContextProposalInput,
  ActivityContextReviewLink,
  ActivityDisposition,
  ActivityReport,
  ActivityReportContent,
} from '../types/activity'

type SourceFilter = 'all' | string
type DispositionFilter = 'all' | ActivityDisposition

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function asReportContent(value: unknown): ActivityReportContent | null {
  if (!isRecord(value) || value.version !== '1' || typeof value.submission_key !== 'string' ||
    typeof value.title !== 'string' || typeof value.task_status !== 'string' || typeof value.outcome !== 'string' ||
    !isStringList(value.evidence_links) || !isStringList(value.artifact_references) ||
    !isStringList(value.unresolved_questions) || !isStringList(value.subjects) || !isStringList(value.projects) ||
    !Array.isArray(value.findings)) return null
  const findings = value.findings.map((finding) => {
    if (!isRecord(finding) || typeof finding.text !== 'string' ||
      (finding.title !== null && typeof finding.title !== 'string') ||
      (finding.derivation !== 'model_interpretation' && finding.derivation !== 'unknown')) return null
    return { title: finding.title as string | null, text: finding.text, derivation: finding.derivation }
  })
  if (findings.some((finding) => finding === null) ||
    (value.suggested_follow_up !== null && typeof value.suggested_follow_up !== 'string') ||
    (value.occurred_at !== null && typeof value.occurred_at !== 'string') ||
    (value.native_task_url !== null && typeof value.native_task_url !== 'string') ||
    (value.markdown_body !== null && typeof value.markdown_body !== 'string')) return null
  return {
    version: '1', submission_key: value.submission_key, title: value.title,
    task_status: value.task_status, outcome: value.outcome,
    findings: findings as ActivityReportContent['findings'], evidence_links: value.evidence_links,
    artifact_references: value.artifact_references, unresolved_questions: value.unresolved_questions,
    suggested_follow_up: value.suggested_follow_up as string | null, subjects: value.subjects,
    projects: value.projects, occurred_at: value.occurred_at as string | null,
    native_task_url: value.native_task_url as string | null,
    markdown_body: value.markdown_body as string | null,
  }
}

function asReport(value: unknown): ActivityReport | null {
  if (!isRecord(value) || typeof value.id !== 'string' ||
    (value.partition !== 'production' && value.partition !== 'sandbox') ||
    typeof value.client_id !== 'string' || typeof value.client_display_name !== 'string' ||
    typeof value.principal !== 'string' || typeof value.received_at !== 'string' ||
    !['new', 'reviewed', 'dismissed'].includes(String(value.disposition))) return null
  const report = asReportContent(value.report)
  return report ? { ...value as Omit<ActivityReport, 'report' | 'disposition'>, disposition: value.disposition as ActivityDisposition, report } : null
}

function asReview(value: unknown): ContextReview | null {
  if (!isRecord(value) || typeof value.id !== 'string' ||
    (value.partition !== 'production' && value.partition !== 'sandbox') ||
    typeof value.operation !== 'string' || !isRecord(value.proposal) || !isRecord(value.evidence) ||
    !isRecord(value.expected_revisions) || !Array.isArray(value.reason_codes) ||
    !['pending', 'accepted', 'rejected', 'stale'].includes(String(value.decision)) ||
    (value.action_id !== null && typeof value.action_id !== 'string') ||
    (value.decision_at !== null && typeof value.decision_at !== 'string') || typeof value.created_at !== 'string') return null
  return value as unknown as ContextReview
}

function asLinks(value: unknown): ActivityContextReviewLink[] | null {
  if (!Array.isArray(value)) return null
  const links = value.map((item) => {
    if (!isRecord(item) || typeof item.finding_reference !== 'string') return null
    const review = asReview(item.review)
    return review ? { finding_reference: item.finding_reference, review } : null
  })
  return links.some((link) => link === null) ? null : links as ActivityContextReviewLink[]
}

async function responseBody(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => null)
  if (response.ok) return body
  if (isRecord(body) && typeof body.detail === 'string') throw new Error(body.detail)
  throw new Error(`Request failed (${response.status}).`)
}

export interface UseActivityInboxResult {
  reports: ActivityReport[]
  detail: ActivityReport | null
  linkedReviews: ActivityContextReviewLink[]
  selectedReportId: string | null
  sourceFilter: SourceFilter
  dispositionFilter: DispositionFilter
  sources: Array<{ id: string; label: string }>
  isLoading: boolean
  isDetailLoading: boolean
  mutation: 'disposition' | 'proposal' | null
  error: string | null
  setSourceFilter: (value: SourceFilter) => void
  setDispositionFilter: (value: DispositionFilter) => void
  selectReport: (reportId: string | null) => void
  refresh: () => Promise<void>
  setDisposition: (disposition: ActivityDisposition) => Promise<boolean>
  proposeContext: (input: ActivityContextProposalInput) => Promise<ContextReview | null>
}

export function useActivityInbox(enabled: boolean): UseActivityInboxResult {
  const [reports, setReports] = useState<ActivityReport[]>([])
  const [detail, setDetail] = useState<ActivityReport | null>(null)
  const [linkedReviews, setLinkedReviews] = useState<ActivityContextReviewLink[]>([])
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [dispositionFilter, setDispositionFilter] = useState<DispositionFilter>('all')
  const [isLoading, setIsLoading] = useState(false)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [mutation, setMutation] = useState<'disposition' | 'proposal' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const listRequest = useRef(0)
  const detailRequest = useRef(0)

  const loadList = useCallback(async (): Promise<void> => {
    if (!enabled) return
    const request = ++listRequest.current
    setIsLoading(true)
    try {
      const body = await fetch(API_ENDPOINTS.activityReports({
        clientId: sourceFilter === 'all' ? undefined : sourceFilter,
        disposition: dispositionFilter === 'all' ? undefined : dispositionFilter,
        limit: 100,
      })).then(responseBody)
      if (!Array.isArray(body)) throw new Error('The activity list response was invalid.')
      const next = body.map(asReport)
      if (next.some((item) => item === null)) throw new Error('The activity list response was invalid.')
      if (request !== listRequest.current) return
      const parsed = next as ActivityReport[]
      setReports(parsed)
      setSelectedReportId((current) => parsed.some((report) => report.id === current) ? current : parsed[0]?.id ?? null)
      setError(null)
    } catch (caught) {
      if (request === listRequest.current) setError(caught instanceof Error ? caught.message : 'Activity inbox is unavailable.')
    } finally {
      if (request === listRequest.current) setIsLoading(false)
    }
  }, [dispositionFilter, enabled, sourceFilter])

  const loadDetail = useCallback(async (reportId: string): Promise<void> => {
    if (!enabled) return
    const request = ++detailRequest.current
    setIsDetailLoading(true)
    try {
      const [reportBody, reviewsBody] = await Promise.all([
        fetch(API_ENDPOINTS.activityReport(reportId)).then(responseBody),
        fetch(API_ENDPOINTS.activityReportContextReviews(reportId)).then(responseBody),
      ])
      const report = asReport(reportBody)
      const reviews = asLinks(reviewsBody)
      if (!report || !reviews) throw new Error('The selected activity report was invalid.')
      if (request !== detailRequest.current) return
      setDetail(report)
      setLinkedReviews(reviews)
      setError(null)
    } catch (caught) {
      if (request === detailRequest.current) {
        setDetail(null)
        setLinkedReviews([])
        setError(caught instanceof Error ? caught.message : 'The selected activity report is unavailable.')
      }
    } finally {
      if (request === detailRequest.current) setIsDetailLoading(false)
    }
  }, [enabled])

  useEffect(() => { void loadList() }, [loadList])
  useEffect(() => {
    if (selectedReportId) void loadDetail(selectedReportId)
    else {
      setDetail(null)
      setLinkedReviews([])
    }
  }, [loadDetail, selectedReportId])

  const refresh = useCallback(async (): Promise<void> => {
    await Promise.all([loadList(), selectedReportId ? loadDetail(selectedReportId) : Promise.resolve()])
  }, [loadDetail, loadList, selectedReportId])

  const setDisposition = useCallback(async (disposition: ActivityDisposition): Promise<boolean> => {
    if (!detail) return false
    setMutation('disposition')
    try {
      const body = await fetch(API_ENDPOINTS.activityReport(detail.id), {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ disposition }),
      }).then(responseBody)
      const updated = asReport(body)
      if (!updated) throw new Error('The activity disposition response was invalid.')
      setDetail(updated)
      setReports((current) => current.map((report) => report.id === updated.id ? updated : report))
      setError(null)
      if (dispositionFilter !== 'all' && dispositionFilter !== disposition) await loadList()
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The report disposition could not be updated.')
      return false
    } finally {
      setMutation(null)
    }
  }, [detail, dispositionFilter, loadList])

  const proposeContext = useCallback(async (input: ActivityContextProposalInput): Promise<ContextReview | null> => {
    if (!detail) return null
    setMutation('proposal')
    try {
      const body = await fetch(API_ENDPOINTS.activityReportContextProposals(detail.id), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
      }).then(responseBody)
      const review = asReview(body)
      if (!review) throw new Error('The context proposal response was invalid.')
      await loadDetail(detail.id)
      setError(null)
      return review
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The context proposal could not be created.')
      return null
    } finally {
      setMutation(null)
    }
  }, [detail, loadDetail])

  const sources = useMemo(() => {
    const labels = new Map<string, string>()
    reports.forEach((report) => labels.set(report.client_id, report.client_display_name))
    return [...labels.entries()]
      .map(([id, label]) => ({ id, label }))
      .sort((left, right) => left.label.localeCompare(right.label))
  }, [reports])

  return {
    reports, detail, linkedReviews, selectedReportId, sourceFilter,
    dispositionFilter, sources, isLoading, isDetailLoading, mutation, error,
    setSourceFilter, setDispositionFilter, selectReport: setSelectedReportId, refresh,
    setDisposition, proposeContext,
  }
}
