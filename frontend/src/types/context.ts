export type ContextStatus = 'active' | 'conflicting' | 'superseded' | 'retracted'
export type ContextKind = 'idea' | 'preference' | 'decision' | 'goal' | 'fact' | 'constraint' | 'note' | 'observation'

export interface ContextEntity {
  id: string
  name: string
  aliases: string[]
  merged_into_entity_id: string | null
}

export interface ContextRecord {
  id: string
  partition: 'production' | 'sandbox'
  kind: ContextKind
  text: string
  status: ContextStatus
  subject: ContextEntity | null
  predicate: string | null
  object_entity: ContextEntity | null
  object_value: string | null
  effective_at: string | null
  supersedes_record_id: string | null
  created_at: string
  updated_at: string
}

export interface ContextSource {
  id: string
  kind: 'conversation_message' | 'manual'
  locator: string
  original_text: string
  created_at: string
}

export interface ContextRecordDetail extends ContextRecord {
  sources: ContextSource[]
  superseded_by: string[]
  related_records: ContextRecord[]
}

export interface RetrievalStatus {
  enabled: boolean
  mode: 'disabled' | 'fts_only' | 'semantic'
  state: 'disabled' | 'unprepared' | 'preparing' | 'ready' | 'degraded'
  indexed_items: number
  embedding_items: number
  pending_items: number
  last_prepared_at: string | null
  error_category: string | null
  model_fingerprint: string | null
}

export type ContextAction =
  | { operation: 'retract' | 'restore' | 'set_current'; record_id: string }
  | { operation: 'correct'; record_id: string; capture: ContextCaptureInput }
  | { operation: 'add_alias'; entity_id: string; alias: string }
  | { operation: 'merge_entities'; source_entity_id: string; target_entity_id: string }

export interface ContextCaptureInput {
  kind: ContextKind
  text: string
  subject?: string | null
  predicate?: string | null
  object_entity?: string | null
  object_value?: string | null
  effective_at?: string | null
}
