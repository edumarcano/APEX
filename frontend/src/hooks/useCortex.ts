import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { AgentStatus } from '../types/telemetry'

export type { AgentKey, AgentStatus, ToolOutputItem } from '../types/telemetry'

const AGENT_POLL_INTERVAL_MS = 4_000

export interface UseCortexResult {
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isLocalModelActionPending: boolean
  verifyingCloudModel: string | null
  refreshAgentsStatus: () => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  loadLocalModel: (modelId?: string) => Promise<boolean>
  verifyCloudAgent: (modelId: string) => Promise<boolean>
}

function parseAgentStatusList(body: unknown): AgentStatus[] {
  if (!body || typeof body !== 'object') return []
  const record = body as Record<string, unknown>
  if (record.key !== 'apex' || !Array.isArray(record.model_catalog)) return []
  const catalog = record.model_catalog as AgentStatus['model_catalog']
  const selected = catalog.find((entry) => entry.model_id === record.selected_model) ?? catalog[0]
  if (!selected) return []
  return [{
    key: 'apex',
    display_name: typeof record.display_name === 'string' ? record.display_name : 'Apex Agent',
    description: typeof record.description === 'string' ? record.description : '',
    configured_model: selected.model_id,
    native_tools: {}, provider: selected.provider,
    sort_order: 0, capabilities: ['APEX', 'Personal operations'], runtime: selected.runtime,
    model_stability: selected.stability, reasoning_options: selected.reasoning_options ?? null,
    default_reasoning: selected.default_reasoning ?? null, context_window: selected.default_context_window ?? null,
    context_window_options: selected.context_options ?? null, context_window_high_resource_options: selected.high_resource_context_options ?? null,
    default_context_window: selected.default_context_window ?? null, reasoning_mode: selected.default_reasoning_mode ?? null,
    reasoning_mode_options: selected.reasoning_modes ?? null, default_reasoning_mode: selected.default_reasoning_mode ?? null,
    status: selected.status ?? 'configured', status_source: selected.status_source ?? 'configuration', status_checked_at: selected.status_checked_at ?? null,
    provider_account_tier: null, pricing: selected.pricing ?? { currency: 'USD', pricing_version: 'unknown', billing_basis: selected.runtime === 'local' ? 'local' : 'standard', input_per_million: 0, output_per_million: 0, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null },
    active: selected.active ?? false, loading: selected.loading ?? false, reason: selected.reason ?? null, idle_unload_remaining_seconds: null, loaded_model: selected.loaded_model ?? null, model_catalog: catalog,
  }]
}

export function useCortex(agentsPollingEnabled = false): UseCortexResult {
  const [agentsStatus, setAgentsStatus] = useState<AgentStatus[]>([])
  const [agentsStatusHydrated, setAgentsStatusHydrated] = useState(false)
  const [isLocalModelActionPending, setIsLocalModelActionPending] = useState(false)
  const [verifyingCloudModel, setVerifyingCloudModel] = useState<string | null>(null)
  const fetchGenerationRef = useRef(0)

  const refreshAgentsStatus = useCallback(async (): Promise<void> => {
    const generation = ++fetchGenerationRef.current
    try {
      const response = await fetch(API_ENDPOINTS.cortexAgent)
      if (!response.ok || generation !== fetchGenerationRef.current) return
      const parsed = parseAgentStatusList(await response.json())
      if (generation !== fetchGenerationRef.current) return
      setAgentsStatus(parsed)
      setAgentsStatusHydrated(true)
    } catch (error) {
      if (generation === fetchGenerationRef.current) console.warn(`[useCortex] Agent status fetch failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }, [])

  useEffect(() => {
    if (!agentsPollingEnabled) return
    let cancelled = false
    let timeout: number | undefined
    const poll = async (): Promise<void> => {
      if (cancelled) return
      if (!document.hidden) await refreshAgentsStatus()
      if (!cancelled) timeout = window.setTimeout(() => { void poll() }, AGENT_POLL_INTERVAL_MS)
    }
    void poll()
    return () => { cancelled = true; if (timeout !== undefined) window.clearTimeout(timeout) }
  }, [agentsPollingEnabled, refreshAgentsStatus])

  const unloadLocalModel = useCallback(async (): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const response = await fetch(API_ENDPOINTS.cortexLocalModelUnload, { method: 'POST' })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch (error) {
      console.warn(`[useCortex] Local model unload failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
      return false
    } finally { setIsLocalModelActionPending(false) }
  }, [isLocalModelActionPending, refreshAgentsStatus])

  const loadLocalModel = useCallback(async (modelId?: string): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const resolvedModelId = modelId ?? agentsStatus[0]?.model_catalog.find((model) => model.runtime === 'local')?.model_id
      if (!resolvedModelId) return false
      const response = await fetch(API_ENDPOINTS.cortexLocalModelLoad, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: resolvedModelId }) })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch (error) {
      console.warn(`[useCortex] Local model load failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
      return false
    } finally { setIsLocalModelActionPending(false) }
  }, [agentsStatus, isLocalModelActionPending, refreshAgentsStatus])

  const verifyCloudAgent = useCallback(async (modelId: string): Promise<boolean> => {
    if (verifyingCloudModel) return false
    setVerifyingCloudModel(modelId)
    try {
      const response = await fetch(API_ENDPOINTS.cortexModelVerify, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: modelId }) })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch { return false } finally { setVerifyingCloudModel(null) }
  }, [refreshAgentsStatus, verifyingCloudModel])

  return { agentsStatus, agentsStatusHydrated, isLocalModelActionPending, verifyingCloudModel, refreshAgentsStatus, unloadLocalModel, loadLocalModel, verifyCloudAgent }
}
