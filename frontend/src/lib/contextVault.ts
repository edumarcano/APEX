import { API_ENDPOINTS } from './api'
import type {
  ContextEntity,
  ContextKind,
  ContextRecord,
  ContextStatus,
  ContextVaultPreview,
  ContextVaultStatus,
} from '../types/context'
import type { ContextVaultScopeSettings } from '../types/settings'

const KINDS: readonly ContextKind[] = [
  'idea', 'preference', 'decision', 'goal', 'fact', 'constraint', 'note', 'observation',
]
const STATUSES: readonly ContextStatus[] = ['active', 'conflicting', 'superseded', 'retracted']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export class ContextVaultRequestError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function readResponse(response: Response): Promise<unknown> {
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const message = isRecord(body) && typeof body.detail === 'string'
      ? body.detail
      : `Context vault request failed (${response.status}). Try again.`
    throw new ContextVaultRequestError(message, response.status)
  }
  return body
}

function parseScopeStatus(value: unknown): ContextVaultStatus['scopes'][number] | null {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.name !== 'string' ||
    typeof value.enabled !== 'boolean' || typeof value.selected_entity_count !== 'number' ||
    typeof value.record_count !== 'number' || typeof value.excluded_record_count !== 'number' ||
    typeof value.include_sensitive !== 'boolean') return null
  return value as unknown as ContextVaultStatus['scopes'][number]
}

export function parseContextVaultStatus(value: unknown): ContextVaultStatus | null {
  if (!isRecord(value) || typeof value.enabled !== 'boolean' ||
    typeof value.destination_configured !== 'boolean' || typeof value.export_restricted !== 'boolean' ||
    !(value.restriction_code === null || typeof value.restriction_code === 'string') ||
    typeof value.dirty !== 'boolean' || typeof value.refreshing !== 'boolean' ||
    !(value.knowledge_revision === null || typeof value.knowledge_revision === 'number') ||
    !(value.exported_revision === null || typeof value.exported_revision === 'number') ||
    !(value.last_attempt_at === null || typeof value.last_attempt_at === 'string') ||
    typeof value.attempt_count !== 'number' || typeof value.owned_file_count !== 'number' ||
    typeof value.changed_file_count !== 'number' || typeof value.removed_file_count !== 'number' ||
    !(value.last_success_at === null || typeof value.last_success_at === 'string') ||
    !(value.last_error_code === null || typeof value.last_error_code === 'string') ||
    !(value.destination_path === null || typeof value.destination_path === 'string') ||
    !Array.isArray(value.retained_destinations) ||
    !value.retained_destinations.every((item) => typeof item === 'string') ||
    !Array.isArray(value.scopes)) return null
  const scopes = value.scopes.map(parseScopeStatus)
  if (scopes.some((scope) => scope === null)) return null
  return { ...value, scopes } as unknown as ContextVaultStatus
}

function parsePreviewRecord(value: unknown): ContextVaultPreview['records'][number] | null {
  if (!isRecord(value) || typeof value.record_id !== 'string' ||
    typeof value.kind !== 'string' || !(KINDS as readonly string[]).includes(value.kind) ||
    typeof value.text !== 'string' || typeof value.status !== 'string' ||
    !(STATUSES as readonly string[]).includes(value.status) || typeof value.sensitive !== 'boolean' ||
    typeof value.eligible !== 'boolean' || !Array.isArray(value.exclusion_reasons) ||
    !value.exclusion_reasons.every((reason) => typeof reason === 'string') ||
    typeof value.projected_path !== 'string') return null
  return value as unknown as ContextVaultPreview['records'][number]
}

export function parseContextVaultPreview(value: unknown): ContextVaultPreview | null {
  const comparisonStates = ['compared', 'no_prior_export', 'destination_unconfigured', 'export_restricted', 'unavailable']
  if (!isRecord(value) || typeof value.scope_id !== 'string' || typeof value.scope_name !== 'string' ||
    typeof value.vault_enabled !== 'boolean' || typeof value.scope_enabled !== 'boolean' ||
    typeof value.hypothetical_enabled !== 'boolean' || typeof value.destination_configured !== 'boolean' ||
    typeof value.export_restricted !== 'boolean' ||
    !(value.restriction_code === null || typeof value.restriction_code === 'string') ||
    typeof value.projection_comparison_state !== 'string' || !comparisonStates.includes(value.projection_comparison_state) ||
    typeof value.candidate_count !== 'number' || typeof value.eligible_count !== 'number' ||
    !Array.isArray(value.records) || !Array.isArray(value.selection_issues) || !Array.isArray(value.projection_changes)) return null
  const records = value.records.map(parsePreviewRecord)
  if (records.some((item) => item === null)) return null
  const selectionIssues = value.selection_issues.map((issue) => {
    if (!isRecord(issue) || typeof issue.entity_id !== 'string' || typeof issue.reason_code !== 'string' ||
      !(issue.replacement_entity_id === null || typeof issue.replacement_entity_id === 'string')) return null
    return issue
  })
  if (selectionIssues.some((issue) => issue === null)) return null
  const projectionChanges = value.projection_changes.map((change) => {
    if (!isRecord(change) || typeof change.path !== 'string' ||
      (change.action !== 'added' && change.action !== 'updated' && change.action !== 'removed')) return null
    return change
  })
  if (projectionChanges.some((change) => change === null)) return null
  return { ...value, records, selection_issues: selectionIssues, projection_changes: projectionChanges } as unknown as ContextVaultPreview
}

function parseEntity(value: unknown): ContextEntity | null {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.name !== 'string' ||
    !Array.isArray(value.aliases) || !value.aliases.every((alias) => typeof alias === 'string') ||
    !(value.merged_into_entity_id === null || typeof value.merged_into_entity_id === 'string')) return null
  return value as unknown as ContextEntity
}

function parseContextRecord(value: unknown): ContextRecord | null {
  if (!isRecord(value) || typeof value.id !== 'string' ||
    (value.partition !== 'production' && value.partition !== 'sandbox') ||
    typeof value.kind !== 'string' || !(KINDS as readonly string[]).includes(value.kind) ||
    typeof value.text !== 'string' || typeof value.status !== 'string' ||
    !(STATUSES as readonly string[]).includes(value.status) ||
    !(value.subject === null || parseEntity(value.subject)) ||
    !(value.object_entity === null || parseEntity(value.object_entity)) ||
    !(value.predicate === null || typeof value.predicate === 'string') ||
    !(value.object_value === null || typeof value.object_value === 'string') ||
    !(value.effective_at === null || typeof value.effective_at === 'string') ||
    !(value.supersedes_record_id === null || typeof value.supersedes_record_id === 'string') ||
    typeof value.created_at !== 'string' || typeof value.updated_at !== 'string' ||
    typeof value.sensitive !== 'boolean') return null
  return value as unknown as ContextRecord
}

export async function fetchContextVaultStatus(): Promise<ContextVaultStatus> {
  const parsed = parseContextVaultStatus(await readResponse(await fetch(API_ENDPOINTS.cortexVault)))
  if (!parsed) throw new Error('Context vault status is unavailable.')
  return parsed
}

export async function previewContextVault(candidateScope: ContextVaultScopeSettings): Promise<ContextVaultPreview> {
  const parsed = parseContextVaultPreview(await readResponse(await fetch(API_ENDPOINTS.cortexVaultPreview, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_scope: candidateScope }),
  })))
  if (!parsed) throw new Error('Context vault preview is unavailable.')
  return parsed
}

export async function refreshContextVault(): Promise<ContextVaultStatus> {
  const parsed = parseContextVaultStatus(await readResponse(await fetch(API_ENDPOINTS.cortexVaultRefresh, { method: 'POST' })))
  if (!parsed) throw new Error('Context vault refresh status is unavailable.')
  return parsed
}

export async function removeContextVaultCopies(): Promise<ContextVaultStatus> {
  const parsed = parseContextVaultStatus(await readResponse(await fetch(API_ENDPOINTS.cortexVaultCopies, { method: 'DELETE' })))
  if (!parsed) throw new Error('Context vault removal status is unavailable.')
  return parsed
}

export async function searchContextVaultEntities(query: string): Promise<ContextEntity[]> {
  const params = new URLSearchParams({ limit: '50' })
  if (query.trim()) params.set('q', query.trim())
  const body = await readResponse(await fetch(`${API_ENDPOINTS.cortexContextEntities}?${params}`))
  if (!Array.isArray(body)) throw new Error('Entity search is unavailable.')
  const entities = body.map(parseEntity)
  if (entities.some((entity) => entity === null)) throw new Error('Entity search response was malformed.')
  return entities as ContextEntity[]
}

export async function searchContextVaultRecords(query: string): Promise<ContextRecord[]> {
  const params = new URLSearchParams({ limit: '100' })
  for (const status of STATUSES) params.append('status', status)
  if (query.trim()) params.set('q', query.trim())
  const body = await readResponse(await fetch(`${API_ENDPOINTS.cortexContext}?${params}`))
  if (!Array.isArray(body)) throw new Error('Record search is unavailable.')
  const records = body.map(parseContextRecord)
  if (records.some((record) => record === null)) throw new Error('Record search response was malformed.')
  return records as ContextRecord[]
}
