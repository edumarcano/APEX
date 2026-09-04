export type RunStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type RunStopReason =
  | 'end_turn'
  | 'operator_cancelled'
  | 'max_elapsed_seconds'
  | 'max_total_tokens'
  | 'max_retries'
  | 'max_model_turns'
  | 'max_tool_calls'
  | 'provider_error'
  | 'tool_error'
  | 'runtime_error'
  | 'resource_exhaustion'
  | 'interrupted_by_restart'
  | 'internal_error'

export type UsageQuality = 'reported' | 'estimated' | 'unavailable'
export type RunPartition = 'production' | 'sandbox'
export type FinalMessageStatus = 'completed' | 'failed' | 'interrupted'

export interface RunLimitSnapshot {
  max_elapsed_seconds: number
  max_total_tokens: number
  max_retries: number
  max_model_turns: number
  max_tool_calls: number
}

export interface RunRuntimeMeasurements {
  queue_duration_ms?: number | null
  prompt_eval_duration_ms?: number | null
  eval_duration_ms?: number | null
  total_duration_ms?: number | null
  ttft_ms?: number | null
  prompt_eval_count?: number | null
  eval_count?: number | null
  tokens_per_second?: number | null
}

export interface RunCompletionEvidence {
  final_message_status?: FinalMessageStatus | null
  answer_persisted: boolean
  tool_outcome_counts: Record<string, number>
  action_ids: string[]
}

export interface RunError {
  code: string
  message: string
}

export interface RunRecord {
  id: string
  conversation_id: string
  partition: RunPartition
  user_message_id: string
  agent_message_id: string
  requested_model: string
  resolved_model: string | null
  provider: string | null
  runtime: string | null
  status: RunStatus
  stop_reason: RunStopReason | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
  limit_snapshot: RunLimitSnapshot
  turns_count: number
  tool_calls_count: number
  retries_count: number
  total_tokens: number
  elapsed_seconds: number
  usage_quality: UsageQuality
  runtime_measurements: RunRuntimeMeasurements
  evidence: RunCompletionEvidence
  trace_id: string | null
  error: RunError | null
}

export type RunEventType =
  | 'run.snapshot'
  | 'run.status'
  | 'model.started'
  | 'model.completed'
  | 'response.delta'
  | 'response.reset'
  | 'response.completed'
  | 'tool.started'
  | 'tool.completed'
  | 'action.proposed'
  | 'usage.updated'
  | 'runtime.updated'
  | 'run.completed'

export interface RunEvent {
  sequence: number
  run_id: string
  type: RunEventType
  timestamp: string
  payload: Record<string, unknown>
}
