export type BriefingProfileId = 'daily' | 'catch_up' | 'deep'

export type BriefingProfileSummary = {
  id: BriefingProfileId
  label: string
  purpose: string
  investigation_required: boolean
  available: boolean
  unavailable_reason: string | null
}

export type BriefingSessionStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export type BriefingStage = 'preparing' | 'collecting' | 'selecting' | 'investigating' | 'synthesizing' | 'persisting'

export type BriefingStageProgress = {
  stage: BriefingStage
  state: 'started' | 'completed' | 'failed' | 'cancelled'
}

export type BriefingInvestigationMetadata = {
  status: 'completed' | 'limited' | 'no_read_needed'
  offered_tool_names: string[]
  used_tool_names: string[]
  result_count: number
  turns_used: number
  tool_calls_used: number
  time_budget_seconds: number
  limitations: string[]
}

export type BriefingSessionSummary = {
  id: string
  profile_id: BriefingProfileId
  model_id: string
  conversation_id: string
  run_id: string
  run_status: BriefingSessionStatus
  created_at: string
  presented_at: string | null
}

export type BriefingEvidence = {
  id: string
  source: string
  source_id: string
  identity_kind: 'provider' | 'content' | 'masked' | 'fixture' | 'unknown'
  revision: string | null
  revision_kind: 'provider' | 'content' | 'none'
  semantic_fingerprint?: string | null
  normalization_version?: number | null
  comparison_role?: 'current' | 'historical'
  change_kind?: 'new' | 'changed' | 'time_sensitive' | 'unchanged' | 'not_comparable' | null
  comparison_pair_id?: string | null
  previously_included?: boolean
  all_day?: boolean
  time_zone?: string | null
  effective_until?: string | null
  observed_at: string | null
  effective_at: string | null
  trust: 'observed' | 'accepted' | 'pending' | 'untrusted' | 'unknown'
  content: string | null
  record_reference: { kind: string; id: string } | null
  included_in_synthesis: boolean
  available: boolean
  unavailable_reason: string | null
}

export type BriefingArtifactItem = {
  id: string
  category: 'observation' | 'accepted_context' | 'pending_review' | 'external_report' | 'analysis' | 'suggestion'
  title: string
  body: string
  evidence_ids: string[]
  record_references: Array<{ kind: string; id: string }>
}

export type BriefingComparisonSource = {
  source: string
  status: 'compared' | 'limited' | 'initial' | 'unavailable' | 'disabled'
  baseline_session_id: string | null
  baseline_snapshot_at: string | null
  current_snapshot_at: string | null
  reason: string | null
}

export type BriefingComparison = {
  outcome: 'initial' | 'compared' | 'limited' | 'no_change'
  summary: string
  sources: BriefingComparisonSource[]
  material_change_count: number
  no_material_changes: boolean
}

export type BriefingArtifact = {
  schema_version: 1
  session_id: string
  created_at: string
  sections: Array<{
    id: string
    title: string
    items: BriefingArtifactItem[]
  }>
  coverage: Array<{
    source: string
    scope: string
    scope_key?: string | null
    normalization_version?: number | null
    status: 'complete' | 'partial' | 'unavailable' | 'disabled' | 'failed'
    observed_at: string | null
    window_start: string | null
    window_end: string | null
    freshness_seconds: number | null
    truncated: boolean
    reason: string | null
  }>
  limitations: string[]
  comparison?: BriefingComparison | null
  investigation?: BriefingInvestigationMetadata | null
}

export type BriefingSessionDetail = {
  id: string
  conversation_id: string
  opening_message_id: string
  run_id: string
  run_status: BriefingSessionStatus
  run_error_code: string | null
  configuration: {
    profile: { id: BriefingProfileId; label: string; purpose: string; definition_version: number }
    model: {
      model_id: string
      provider: string
      runtime: string
      reasoning: string | null
      context_window: number | null
      local_reasoning_mode: string | null
    }
    origin: 'hud' | 'cli'
    execution_kind: 'model' | 'demo'
  }
  artifact: BriefingArtifact | null
  evidence_count: number
  evidence_ids: string[]
  created_at: string
  presented_at: string | null
  speech_status: 'not_requested' | 'ready' | 'unavailable'
  active_stage?: BriefingStageProgress | null
}

export type BriefingSessionWithEvidence = BriefingSessionDetail & {
  evidence: BriefingEvidence[]
}
