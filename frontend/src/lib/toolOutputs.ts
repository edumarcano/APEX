import type { ToolOutputItem } from '../types/telemetry'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export interface ActionProposalToolOutput {
  action_id: string
  status: 'proposed'
  version: number
  risk: 'write' | 'destructive'
  summary: string
  target: string
}

export function parseActionProposalToolOutput(value: unknown): ActionProposalToolOutput | null {
  if (!isRecord(value)) return null
  if (
    typeof value.action_id !== 'string' ||
    value.status !== 'proposed' ||
    typeof value.version !== 'number' ||
    !Number.isInteger(value.version) ||
    (value.risk !== 'write' && value.risk !== 'destructive') ||
    typeof value.summary !== 'string' ||
    typeof value.target !== 'string'
  ) return null
  return {
    action_id: value.action_id,
    status: value.status,
    version: value.version,
    risk: value.risk,
    summary: value.summary,
    target: value.target,
  }
}

/**
 * Tool results that must stay fully visible wherever results are compacted:
 * failures, pending approvals, and outputs that carry a trust label.
 */
export function requiresFullToolResult(item: ToolOutputItem): boolean {
  if (item.status.toLowerCase() === 'error') return true
  if (parseActionProposalToolOutput(item.output)) return true
  return isRecord(item.output) && typeof item.output.trust === 'string'
}
