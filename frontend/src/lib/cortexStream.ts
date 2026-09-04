import { API_ENDPOINTS } from './api'
import type { RunEvent, RunEventType } from '../types/runs'

export interface ConsumeRunStreamOptions {
  signal?: AbortSignal
  lastEventId?: number
  maxReconnectAttempts?: number
  onEvent?: (event: RunEvent) => void
  onError?: (error: Error) => void
}

export interface ParseSSEBlockResult {
  id?: number
  event?: RunEventType
  data?: Record<string, unknown>
  isComment?: boolean
}

export function parseSSEBlock(block: string): ParseSSEBlockResult | null {
  const lines = block.split(/\r?\n/)
  let id: number | undefined
  let event: RunEventType | undefined
  const dataLines: string[] = []
  let hasContent = false

  for (const line of lines) {
    if (!line.trim()) continue
    if (line.startsWith(':')) {
      // Comment line (heartbeat)
      hasContent = true
      continue
    }
    if (line.startsWith('id:')) {
      hasContent = true
      const parsed = parseInt(line.slice(3).trim(), 10)
      if (!Number.isNaN(parsed)) {
        id = parsed
      }
      continue
    }
    if (line.startsWith('event:')) {
      hasContent = true
      event = line.slice(6).trim() as RunEventType
      continue
    }
    if (line.startsWith('data:')) {
      hasContent = true
      dataLines.push(line.startsWith('data: ') ? line.slice(6) : line.slice(5))
      continue
    }
  }

  if (!hasContent) return null
  if (dataLines.length === 0 && !event && id === undefined) {
    return { isComment: true }
  }

  let data: Record<string, unknown> = {}
  if (dataLines.length > 0) {
    const combined = dataLines.join('\n')
    try {
      data = JSON.parse(combined) as Record<string, unknown>
    } catch {
      data = { raw: combined }
    }
  }

  return { id, event, data }
}

const TERMINAL_EVENT_TYPES: ReadonlySet<string> = new Set(['run.completed'])

export async function* streamRunEvents(
  runId: string,
  options: ConsumeRunStreamOptions = {},
): AsyncGenerator<RunEvent, void> {
  const { signal, maxReconnectAttempts = 3 } = options
  let lastEventId = options.lastEventId ?? 0
  let reconnectAttempts = 0
  let isTerminal = false

  while (!isTerminal) {
    if (signal?.aborted) return

    try {
      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
      }
      if (lastEventId > 0) {
        headers['Last-Event-ID'] = String(lastEventId)
      }

      const response = await fetch(API_ENDPOINTS.cortexRunEvents(runId), {
        headers,
        signal,
      })

      if (!response.ok) {
        throw new Error(`Run event stream failed with HTTP ${response.status}`)
      }

      if (!response.body) {
        throw new Error('Response body is null')
      }

      reconnectAttempts = 0
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      try {
        while (true) {
          if (signal?.aborted) return
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split(/\r?\n\r?\n/)
          // The last element is the remaining incomplete block
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            const parsed = parseSSEBlock(part)
            if (!parsed || parsed.isComment) continue

            const rawData = parsed.data
            const isEnvelope = Boolean(
              rawData &&
              typeof rawData === 'object' &&
              'payload' in rawData &&
              rawData.payload !== null &&
              typeof rawData.payload === 'object' &&
              !Array.isArray(rawData.payload)
            )

            const eventSequence = (isEnvelope && typeof rawData?.sequence === 'number' ? rawData.sequence : undefined)
              ?? parsed.id
              ?? (lastEventId + 1)
            lastEventId = eventSequence

            const event: RunEvent = {
              sequence: eventSequence,
              run_id: (isEnvelope && typeof rawData?.run_id === 'string' ? rawData.run_id : undefined) ?? runId,
              type: (isEnvelope && typeof rawData?.type === 'string' ? (rawData.type as RunEventType) : undefined)
                ?? parsed.event
                ?? 'run.status',
              timestamp: (isEnvelope && typeof rawData?.timestamp === 'string' ? rawData.timestamp : undefined)
                ?? new Date().toISOString(),
              payload: (isEnvelope ? (rawData!.payload as Record<string, unknown>) : rawData) ?? {},
            }

            options.onEvent?.(event)
            yield event

            if (TERMINAL_EVENT_TYPES.has(event.type)) {
              isTerminal = true
              return
            }
          }
        }
      } finally {
        reader.releaseLock?.()
      }

      // If the stream closed naturally without a terminal event:
      if (!isTerminal) {
        // If max reconnects exceeded, stop
        if (reconnectAttempts >= maxReconnectAttempts) {
          return
        }
        reconnectAttempts++
        await new Promise((resolve) => setTimeout(resolve, 200 * reconnectAttempts))
      }
    } catch (err) {
      if (signal?.aborted) return

      const error = err instanceof Error ? err : new Error(String(err))
      options.onError?.(error)

      reconnectAttempts++
      if (reconnectAttempts > maxReconnectAttempts) {
        throw error
      }
      await new Promise((resolve) => setTimeout(resolve, 300 * reconnectAttempts))
    }
  }
}
