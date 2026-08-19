import { useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { AgentKey, CloudEffort, ToolPreflightEstimate } from '../types/telemetry'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
function parsePreflight(value: unknown): ToolPreflightEstimate | null {
  if (!isRecord(value) || !isRecord(value.breakdown) || !isRecord(value.selection)) {
    return null
  }
  const breakdown = value.breakdown
  const selection = value.selection
  if (
    value.agent === undefined ||
    typeof breakdown.system_instructions !== 'number' ||
    typeof breakdown.conversation_history !== 'number' ||
    typeof breakdown.hud_context !== 'number' ||
    typeof breakdown.selected_tool_schemas !== 'number' ||
    typeof breakdown.current_prompt !== 'number' ||
    typeof breakdown.total !== 'number' ||
    (breakdown.configured_context_window !== null &&
      typeof breakdown.configured_context_window !== 'number') ||
    (breakdown.reserved_response_tokens !== null &&
      typeof breakdown.reserved_response_tokens !== 'number') ||
    (breakdown.remaining_estimated_capacity !== null &&
      typeof breakdown.remaining_estimated_capacity !== 'number') ||
    typeof breakdown.is_estimate !== 'boolean' ||
    !Array.isArray(selection.requested_tool_names) ||
    !Array.isArray(selection.offered_tool_names) ||
    !Array.isArray(selection.rejected_tool_names) ||
    !Array.isArray(selection.rejected_tools) ||
    typeof selection.selected_schema_tokens !== 'number'
  ) {
    return null
  }
  return {
    agent: value.agent as AgentKey,
    selection: {
      requested_tool_names: selection.requested_tool_names.filter(
        (name): name is string => typeof name === 'string',
      ),
      offered_tool_names: selection.offered_tool_names.filter(
        (name): name is string => typeof name === 'string',
      ),
      rejected_tool_names: selection.rejected_tool_names.filter(
        (name): name is string => typeof name === 'string',
      ),
      rejected_tools: selection.rejected_tools.flatMap((failure) => {
        if (!isRecord(failure)) return []
        if (
          typeof failure.name !== 'string' ||
          typeof failure.code !== 'string' ||
          typeof failure.reason !== 'string'
        ) {
          return []
        }
        return [{ name: failure.name, code: failure.code, reason: failure.reason }]
      }),
      selected_schema_tokens: selection.selected_schema_tokens,
      active_profile_id:
        typeof selection.active_profile_id === 'string'
          ? selection.active_profile_id
          : null,
      active_profile_name:
        typeof selection.active_profile_name === 'string'
          ? selection.active_profile_name
          : null,
    },
    breakdown: {
      system_instructions: breakdown.system_instructions,
      conversation_history: breakdown.conversation_history,
      hud_context: breakdown.hud_context,
      ...(typeof breakdown.retrieved_context === 'number' ? { retrieved_context: breakdown.retrieved_context } : {}),
      selected_tool_schemas: breakdown.selected_tool_schemas,
      current_prompt: breakdown.current_prompt,
      total: breakdown.total,
      configured_context_window:
        typeof breakdown.configured_context_window === 'number'
          ? breakdown.configured_context_window
          : null,
      reserved_response_tokens:
        typeof breakdown.reserved_response_tokens === 'number'
          ? breakdown.reserved_response_tokens
          : null,
      remaining_estimated_capacity:
        typeof breakdown.remaining_estimated_capacity === 'number'
          ? breakdown.remaining_estimated_capacity
          : null,
      is_estimate: breakdown.is_estimate,
    },
    warning: typeof value.warning === 'string' ? value.warning : null,
    can_proceed: value.can_proceed !== false,
  }
}
interface UseToolPreflightOptions {
  agent: AgentKey
  selectedToolNames: string[]
  toolProfileId: string | null
  modelId?: string | null
  effort?: CloudEffort | null
  contextWindow?: number | null
  localReasoningMode?: 'none' | 'focused' | null
  prompt?: string
  conversationId?: string | null
  snapshotId?: string | null
  briefingId?: number | null
  enabled?: boolean
}

export function useToolPreflight({
  agent,
  selectedToolNames,
  toolProfileId,
  modelId = null,
  effort = null,
  contextWindow = null,
  localReasoningMode = null,
  prompt = '',
  conversationId = null,
  snapshotId = null,
  briefingId = null,
  enabled = true,
}: UseToolPreflightOptions): {
  estimate: ToolPreflightEstimate | null
  isLoading: boolean
  error: string | null
} {
  const [estimate, setEstimate] = useState<ToolPreflightEstimate | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestSequence = useRef(0)

  useEffect(() => {
    const requestId = ++requestSequence.current
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A new preflight contract invalidates the prior estimate before its debounced request starts.
    setEstimate(null)
    setError(null)
    setIsLoading(enabled)
    if (!enabled) return
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      if (requestSequence.current !== requestId) return
      setIsLoading(true)
      setError(null)
      void fetch(API_ENDPOINTS.cortexToolPreflight, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          agent,
          ...(modelId ? { model_id: modelId } : {}),
          ...(effort ? { effort } : {}),
          ...(contextWindow ? { context_window: contextWindow } : {}),
          ...(localReasoningMode ? { local_reasoning_mode: localReasoningMode } : {}),
          selected_tool_names: selectedToolNames,
          ...(toolProfileId ? { tool_profile_id: toolProfileId } : {}),
          prompt,
          ...(conversationId ? { conversation_id: conversationId } : {}),
          ...(snapshotId ? { snapshot_id: snapshotId } : {}),
          ...(briefingId != null ? { briefing_id: briefingId } : {}),
        }),
      })
        .then(async (response) => {
          if (!response.ok) {
            const body: unknown = await response.json().catch(() => null)
            if (isRecord(body) && isRecord(body.detail)) {
              const detail = body.detail
              const rejected = Array.isArray(detail.rejected_tools)
                ? detail.rejected_tools.flatMap((failure) => {
                  if (!isRecord(failure) || typeof failure.name !== 'string' || typeof failure.reason !== 'string') return []
                  return `${failure.name}: ${failure.reason}`
                })
                : []
              if (rejected.length > 0) {
                throw new Error(rejected.join(' · '))
              }
              if (typeof detail.message === 'string') throw new Error(detail.message)
            }
            throw new Error(`Tool estimate unavailable (${response.status})`)
          }
          const parsed = parsePreflight(await response.json())
          if (!parsed) throw new Error('APEX returned an invalid tool estimate.')
          if (requestSequence.current === requestId && !controller.signal.aborted) {
            setEstimate(parsed)
          }
        })
        .catch((fetchError: unknown) => {
          if (controller.signal.aborted || requestSequence.current !== requestId) return
          setEstimate(null)
          setError(fetchError instanceof Error ? fetchError.message : 'Tool estimate unavailable.')
        })
        .finally(() => {
          if (!controller.signal.aborted && requestSequence.current === requestId) {
            setIsLoading(false)
          }
        })
    }, 250)
    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [
    agent,
    briefingId,
    contextWindow,
    conversationId,
    effort,
    enabled,
    localReasoningMode,
    modelId,
    prompt,
    selectedToolNames,
    snapshotId,
    toolProfileId,
  ])

  return { estimate, isLoading, error }
}
