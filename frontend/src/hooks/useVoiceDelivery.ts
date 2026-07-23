import { useCallback, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'

export interface UseVoiceDeliveryReturn {
  isSpeaking: boolean
  error: string | null
  speak: (text: string) => Promise<boolean>
}

function errorMessageFromBody(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : null
}

export function useVoiceDelivery(): UseVoiceDeliveryReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const speak = useCallback(async (text: string): Promise<boolean> => {
    if (!text.trim() || inFlightRef.current) return false
    inFlightRef.current = true
    setIsSpeaking(true)
    setError(null)
    try {
      const response = await fetch(API_ENDPOINTS.voiceSpeak, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        body = null
      }
      if (!response.ok) {
        setError(errorMessageFromBody(body) ?? `Voice delivery failed with status ${response.status}`)
        return false
      }
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice delivery failed')
      return false
    } finally {
      inFlightRef.current = false
      setIsSpeaking(false)
    }
  }, [])

  return { isSpeaking, error, speak }
}
