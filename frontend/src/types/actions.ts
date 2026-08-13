export type ActionRisk = 'write' | 'destructive'

export type ActionStatus =
  | 'proposed'
  | 'approved'
  | 'executing'
  | 'verifying'
  | 'verified'
  | 'rejected'
  | 'expired'
  | 'execution_failed'
  | 'verification_failed'
  | 'outcome_unknown'

export interface ActionProposal {
  agent_key: string
  capability_name: string
  arguments: Record<string, unknown>
  target: string
  risk: ActionRisk
  summary: string
  proposed_at: string
  expires_at: string
  proposal_hash: string
}

export interface ActionRecord {
  action_id: string
  proposal: ActionProposal
  status: ActionStatus
  version: number
  updated_at: string
}

export interface ActionEvent {
  action_id: string
  sequence: number
  from_status: ActionStatus | null
  to_status: ActionStatus
  occurred_at: string
  actor: string
  result_code: string
  evidence: Record<string, unknown>
}

export interface ActionDetail extends ActionRecord {
  events: ActionEvent[]
}

export type ActionMutation = 'approve' | 'reject' | 'verify'
