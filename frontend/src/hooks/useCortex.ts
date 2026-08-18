import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { AgentKey, AgentStatus } from '../types/telemetry'

export type { AgentKey, AgentStatus, ToolOutputItem } from '../types/telemetry'

const AGENT_POLL_INTERVAL_MS = 4_000

export interface UseCortexResult {
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isLocalModelActionPending: boolean
  verifyingCloudAgent: AgentKey | null
  refreshAgentsStatus: () => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  loadLocalModel: () => Promise<boolean>
  verifyCloudAgent: (agent: 'panthera') => Promise<boolean>
}

function parseAgentStatusList(body: unknown): AgentStatus[] {
  if (!Array.isArray(body)) return []
  return body.filter((item): item is AgentStatus => {
    if (!item || typeof item !== 'object') return false
    const record = item as Record<string, unknown>
    return (record.key === 'panthera' || record.key === 'felis') && typeof record.display_name === 'string'
  })
}

export function useCortex(agentsPollingEnabled = false): UseCortexResult {
  const [agentsStatus, setAgentsStatus] = useState<AgentStatus[]>([])
  const [agentsStatusHydrated, setAgentsStatusHydrated] = useState(false)
  const [isLocalModelActionPending, setIsLocalModelActionPending] = useState(false)
  const [verifyingCloudAgent, setVerifyingCloudAgent] = useState<AgentKey | null>(null)
  const fetchGenerationRef = useRef(0)

  const refreshAgentsStatus = useCallback(async (): Promise<void> => {
    const generation = ++fetchGenerationRef.current
    try {
      const response = await fetch(API_ENDPOINTS.agents)
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

  const loadLocalModel = useCallback(async (): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const response = await fetch(API_ENDPOINTS.cortexLocalModelLoad, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent: 'felis' }) })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch (error) {
      console.warn(`[useCortex] Local model load failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
      return false
    } finally { setIsLocalModelActionPending(false) }
  }, [isLocalModelActionPending, refreshAgentsStatus])

  const verifyCloudAgent = useCallback(async (agent: 'panthera'): Promise<boolean> => {
    if (verifyingCloudAgent) return false
    setVerifyingCloudAgent(agent)
    try {
      const response = await fetch(API_ENDPOINTS.agentVerify(agent), { method: 'POST' })
      if (!response.ok) return false
      await refreshAgentsStatus()
      return true
    } catch { return false } finally { setVerifyingCloudAgent(null) }
  }, [refreshAgentsStatus, verifyingCloudAgent])

  return { agentsStatus, agentsStatusHydrated, isLocalModelActionPending, verifyingCloudAgent, refreshAgentsStatus, unloadLocalModel, loadLocalModel, verifyCloudAgent }
}
