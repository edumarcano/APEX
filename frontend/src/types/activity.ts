import type { ContextKind, ContextReview } from './context'

export type ActivityDisposition = 'new' | 'reviewed' | 'dismissed'

export interface ActivityFinding {
  title: string | null
  text: string
  derivation: 'model_interpretation' | 'unknown'
}

export interface ActivityReportContent {
  version: '1'
  submission_key: string
  title: string
  task_status: string
  outcome: string
  findings: ActivityFinding[]
  evidence_links: string[]
  artifact_references: string[]
  unresolved_questions: string[]
  suggested_follow_up: string | null
  subjects: string[]
  projects: string[]
  occurred_at: string | null
  native_task_url: string | null
  markdown_body: string | null
}

export interface ActivityReport {
  id: string
  partition: 'production' | 'sandbox'
  client_id: string
  client_display_name: string
  principal: string
  received_at: string
  disposition: ActivityDisposition
  report: ActivityReportContent
}

export interface ActivityContextReviewLink {
  finding_reference: string
  review: ContextReview
}

export interface ActivityContextProposalInput {
  finding_reference: string
  kind: ContextKind
  text: string
  subject?: string
  predicate?: string
  object_value?: string
  effective_at?: string
}
