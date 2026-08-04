import { useCallback, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { SystemState, TtsEngine } from '../types/telemetry'

export interface UseVoiceDeliveryReturn {
  isSpeaking: boolean
  error: string | null
  lastManualEngine: TtsEngine | null
  speak: (text: string) => Promise<boolean>
}

interface ManualDelivery {
  briefingText: string
  engine: TtsEngine
}

function errorMessageFromBody(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : null
}

export function useVoiceDelivery(
  briefingText: string,
  briefingStatus: SystemState,
  isPipelineSpeaking: boolean,
): UseVoiceDeliveryReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastManualDelivery, setLastManualDelivery] = useState<ManualDelivery | null>(null)
  const inFlightRef = useRef(false)
  const lastManualEngine =
    briefingStatus !== 'loading' &&
    !isPipelineSpeaking &&
    lastManualDelivery?.briefingText === briefingText
      ? lastManualDelivery.engine
      : null

  const speak = useCallback(async (text: string): Promise<boolean> => {
    if (!text.trim() || inFlightRef.current) return false
    inFlightRef.current = true
    setIsSpeaking(true)
    setError(null)
    setLastManualDelivery(null)
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
      const engine =
        body && typeof body === 'object'
          ? (body as { resolved_engine?: unknown }).resolved_engine
          : null
      if (engine === 'google' || engine === 'kokoro' || engine === 'pyttsx3') {
        setLastManualDelivery({ briefingText: text, engine })
      } else {
        setError('Voice delivery returned an invalid engine.')
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

  return { isSpeaking, error, lastManualEngine, speak }
}
