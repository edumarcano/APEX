import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'

export type MicrosoftTodoState =
  | 'not-configured'
  | 'disconnected'
  | 'authorizing'
  | 'connected'
  | 'authentication-required'
  | 'degraded'

export interface MicrosoftTodoStatus {
  configured: boolean
  state: MicrosoftTodoState
  permission: 'Tasks.Read'
}

export interface MicrosoftTodoAuthorization {
  state: 'authorizing'
  verification_uri: string
  user_code: string
  expires_at: string
}

const STATES: readonly MicrosoftTodoState[] = [
  'not-configured',
  'disconnected',
  'authorizing',
  'connected',
  'authentication-required',
  'degraded',
]

function parseStatus(value: unknown): MicrosoftTodoStatus | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  if (
    typeof item.configured !== 'boolean' ||
    typeof item.state !== 'string' ||
    !STATES.includes(item.state as MicrosoftTodoState) ||
    item.permission !== 'Tasks.Read'
  ) return null
  return item as unknown as MicrosoftTodoStatus
}

function parseAuthorization(value: unknown): MicrosoftTodoAuthorization | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  if (
    item.state !== 'authorizing' ||
    typeof item.verification_uri !== 'string' ||
    !item.verification_uri.startsWith('https://') ||
    typeof item.user_code !== 'string' ||
    typeof item.expires_at !== 'string'
  ) return null
  return item as unknown as MicrosoftTodoAuthorization
}

export function useMicrosoftTodoStatus(open: boolean) {
  const [status, setStatus] = useState<MicrosoftTodoStatus | null>(null)
  const [authorization, setAuthorization] = useState<MicrosoftTodoAuthorization | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sequence = useRef(0)

  const refresh = useCallback(async () => {
    const requestId = ++sequence.current
    try {
      const response = await fetch(API_ENDPOINTS.microsoftTodoStatus)
      const parsed = response.ok ? parseStatus(await response.json()) : null
      if (requestId === sequence.current) {
        setStatus(parsed)
        setError(parsed ? null : 'Microsoft To Do status is unavailable.')
        if (parsed && parsed.state !== 'authorizing') setAuthorization(null)
      }
    } catch {
      if (requestId === sequence.current) setError('Microsoft To Do status is unavailable.')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const initialTimeout = window.setTimeout(() => void refresh(), 0)
    const interval = window.setInterval(() => void refresh(), 5000)
    return () => {
      window.clearInterval(interval)
      sequence.current += 1
      window.clearTimeout(initialTimeout)
    }
  }, [open, refresh])

  const connect = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(API_ENDPOINTS.microsoftTodoAuth, { method: 'POST' })
      const parsed = response.ok ? parseAuthorization(await response.json()) : null
      if (!parsed) throw new Error()
      setAuthorization(parsed)
      setStatus((current) => current ? { ...current, state: 'authorizing' } : current)
    } catch {
      setError('Microsoft authorization could not be started.')
    } finally {
      setLoading(false)
    }
  }, [])

  const disconnect = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(API_ENDPOINTS.microsoftTodoAuth, { method: 'DELETE' })
      const parsed = response.ok ? parseStatus(await response.json()) : null
      if (!parsed) throw new Error()
      setStatus(parsed)
      setAuthorization(null)
    } catch {
      setError('Microsoft authorization could not be removed.')
    } finally {
      setLoading(false)
    }
  }, [])

  return { status, authorization, loading, error, refresh, connect, disconnect }
}
