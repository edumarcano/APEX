export type BriefingSessionStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export type BriefingSessionSummary = {
  id: string
  profile_id: 'daily'
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
    status: 'complete' | 'partial' | 'unavailable' | 'disabled' | 'failed'
    observed_at: string | null
    window_start: string | null
    window_end: string | null
    freshness_seconds: number | null
    truncated: boolean
    reason: string | null
  }>
  limitations: string[]
}

export type BriefingSessionDetail = {
  id: string
  conversation_id: string
  opening_message_id: string
  run_id: string
  run_status: BriefingSessionStatus
  configuration: {
    profile: { id: 'daily'; label: 'Daily'; purpose: string; definition_version: number }
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
}

export type BriefingSessionWithEvidence = BriefingSessionDetail & {
  evidence: BriefingEvidence[]
}
