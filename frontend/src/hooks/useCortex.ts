import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { CortexAgent, ModelCatalogEntry } from '../types/telemetry'

export type { AgentKey, CortexAgent, ToolOutputItem } from '../types/telemetry'

const AGENT_POLL_INTERVAL_MS = 4_000

export interface UseCortexResult {
  cortexAgent: CortexAgent | null
  modelCatalog: ModelCatalogEntry[]
  cortexAgentHydrated: boolean
  isLocalModelActionPending: boolean
  verifyingCloudModel: string | null
  refreshAgentsStatus: () => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  loadLocalModel: (modelId?: string) => Promise<boolean>
  verifyCloudAgent: (modelId: string) => Promise<boolean>
}

function parseCortexAgent(body: unknown): CortexAgent | null {
  if (!body || typeof body !== 'object') return null
  const record = body as Record<string, unknown>
  if (
    record.key !== 'apex' ||
    typeof record.display_name !== 'string' ||
    typeof record.description !== 'string' ||
    typeof record.selected_model !== 'string' ||
    !Array.isArray(record.model_catalog)
  ) return null
  return {
    key: 'apex',
    display_name: record.display_name,
    description: record.description,
    selected_model: record.selected_model,
    model_catalog: record.model_catalog as ModelCatalogEntry[],
  }
}

export function useCortex(agentsPollingEnabled = false): UseCortexResult {
  const [cortexAgent, setCortexAgent] = useState<CortexAgent | null>(null)
  const [cortexAgentHydrated, setCortexAgentHydrated] = useState(false)
  const [isLocalModelActionPending, setIsLocalModelActionPending] = useState(false)
  const [verifyingCloudModel, setVerifyingCloudModel] = useState<string | null>(null)
  const fetchGenerationRef = useRef(0)

  const refreshAgentsStatus = useCallback(async (): Promise<void> => {
    const generation = ++fetchGenerationRef.current
    try {
      const response = await fetch(API_ENDPOINTS.cortexAgent)
      if (!response.ok || generation !== fetchGenerationRef.current) return
      const parsed = parseCortexAgent(await response.json())
      if (generation !== fetchGenerationRef.current) return
      setCortexAgent(parsed)
      setCortexAgentHydrated(true)
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
      const resolvedModelId = modelId ?? cortexAgent?.model_catalog.find((model) => model.runtime === 'local')?.model_id
      if (!resolvedModelId) return false
      const response = await fetch(API_ENDPOINTS.cortexLocalModelLoad, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: resolvedModelId }) })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch (error) {
      console.warn(`[useCortex] Local model load failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
      return false
    } finally { setIsLocalModelActionPending(false) }
  }, [cortexAgent, isLocalModelActionPending, refreshAgentsStatus])

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

  return {
    cortexAgent,
    modelCatalog: cortexAgent?.model_catalog ?? [],
    cortexAgentHydrated,
    isLocalModelActionPending,
    verifyingCloudModel,
    refreshAgentsStatus,
    unloadLocalModel,
    loadLocalModel,
    verifyCloudAgent,
  }
}
