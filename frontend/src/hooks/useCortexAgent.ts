import { useCallback, useState } from 'react'

const AGENT_QUERY_ENDPOINT = 'http://127.0.0.1:8000/api/v1/agent/query'

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  thought_signature?: string | null
}

export interface ToolResult {
  id: string
  name: string
  output: unknown
}

export interface AgentMessage {
  role: 'user' | 'model' | 'tool'
  content?: string
  tool_calls?: ToolCall[]
  tool_results?: ToolResult[]
}

export interface ToolTraceItem {
  name: string
  status: string
  duration_ms: number
}

export type CortexProfile = 'comet' | 'nova' | 'pulsar'

type BackendProfile = 'comet' | 'nova' | 'pulsar'

interface AgentQueryResponseBody {
  answer?: string
  tool_trace?: ToolTraceItem[]
  error?: string | null
}

function mapProfileToBackend(profile: CortexProfile): BackendProfile {
  return profile === 'pulsar' ? 'pulsar' : profile
}

function parseToolTraceItem(value: unknown): ToolTraceItem | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const name = typeof record.name === 'string' ? record.name : null
  const status = typeof record.status === 'string' ? record.status : null
  const durationMs =
    typeof record.duration_ms === 'number' && Number.isFinite(record.duration_ms)
      ? record.duration_ms
      : null

  if (!name || !status || durationMs === null) {
    return null
  }

  return { name, status, duration_ms: durationMs }
}

function parseAgentQueryResponse(body: unknown): AgentQueryResponseBody {
  if (!body || typeof body !== 'object') {
    return {}
  }

  const record = body as Record<string, unknown>
  const answer = typeof record.answer === 'string' ? record.answer : undefined
  const error =
    typeof record.error === 'string'
      ? record.error
      : record.error === null
        ? null
        : undefined

  const rawTrace = Array.isArray(record.tool_trace) ? record.tool_trace : []
  const tool_trace = rawTrace
    .map(parseToolTraceItem)
    .filter((item): item is ToolTraceItem => item !== null)

  return { answer, tool_trace, error }
}

export interface UseCortexAgentResult {
  history: AgentMessage[]
  isQuerying: boolean
  isOpen: boolean
  latestTrace: ToolTraceItem[]
  error: string | null
  queryCortex: (prompt: string, profile: CortexProfile) => Promise<void>
  resetSession: () => void
  setIsOpen: (open: boolean) => void
}

export function useCortexAgent(): UseCortexAgentResult {
  const [history, setHistory] = useState<AgentMessage[]>([])
  const [isQuerying, setIsQuerying] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [latestTrace, setLatestTrace] = useState<ToolTraceItem[]>([])
  const [error, setError] = useState<string | null>(null)

  const queryCortex = useCallback(
    async (prompt: string, profile: CortexProfile): Promise<void> => {
      const trimmedPrompt = prompt.trim()
      if (!trimmedPrompt) {
        return
      }

      setIsQuerying(true)
      setIsOpen(true)
      setError(null)

      const userMsg: AgentMessage = { role: 'user', content: trimmedPrompt }

      try {
        const response = await fetch(AGENT_QUERY_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: trimmedPrompt,
            profile: mapProfileToBackend(profile),
            history,
          }),
        })

        if (!response.ok) {
          let message = `Agent query failed (${response.status})`
          try {
            const errorBody: unknown = await response.json()
            if (
              errorBody &&
              typeof errorBody === 'object' &&
              'detail' in errorBody &&
              typeof (errorBody as { detail?: unknown }).detail === 'string'
            ) {
              message = (errorBody as { detail: string }).detail
            }
          } catch {
            // Keep default message when error body is not JSON.
          }
          setError(message)
          return
        }

        const body = parseAgentQueryResponse(await response.json())
        const answer = body.answer ?? ''
        const modelMsg: AgentMessage = { role: 'model', content: answer }

        setHistory((prev) => [...prev, userMsg, modelMsg])
        setLatestTrace(body.tool_trace ?? [])

        if (body.error) {
          setError(body.error)
        }
      } catch (fetchError) {
        const message =
          fetchError instanceof Error
            ? fetchError.message
            : 'Failed to reach APEX Cortex.'
        setError(message)
      } finally {
        setIsQuerying(false)
      }
    },
    [history],
  )

  const resetSession = useCallback((): void => {
    setHistory([])
    setLatestTrace([])
    setError(null)
    setIsOpen(false)
  }, [])

  return {
    history,
    isQuerying,
    isOpen,
    latestTrace,
    error,
    queryCortex,
    resetSession,
    setIsOpen,
  }
}
