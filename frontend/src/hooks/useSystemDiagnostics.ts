import { useEffect, useState } from 'react'

import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
  type SystemDiagnostics,
} from '../types/telemetry'

const DIAGNOSTICS_ENDPOINT = 'http://127.0.0.1:8000/api/v1/diagnostics'

export type SystemDiagnosticsState = {
  diagnostics: SystemDiagnostics
  status: 'idle' | 'loading' | 'ready' | 'error'
}

function getNumericField(
  source: Record<string, unknown>,
  key: string,
): number | null {
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function mapDiagnosticsRecord(
  source: Record<string, unknown>,
): SystemDiagnostics {
  return {
    cpu: getNumericField(source, 'cpu'),
    ram: getNumericField(source, 'ram'),
    disk: getNumericField(source, 'disk'),
  }
}

export function useSystemDiagnostics(): SystemDiagnosticsState {
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics>({
    ...DEFAULT_SYSTEM_DIAGNOSTICS,
  })
  const [status, setStatus] = useState<SystemDiagnosticsState['status']>('idle')

  useEffect(() => {
    let cancelled = false

    const pollDiagnostics = async (): Promise<void> => {
      try {
        const response = await fetch(DIAGNOSTICS_ENDPOINT)

        if (cancelled) return

        if (!response.ok) {
          setStatus('error')
          return
        }

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          if (!cancelled) setStatus('error')
          return
        }

        if (cancelled || !body || typeof body !== 'object') return

        setDiagnostics(mapDiagnosticsRecord(body as Record<string, unknown>))
        setStatus('ready')
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    setStatus('loading')
    void pollDiagnostics()

    const intervalId = window.setInterval(() => {
      void pollDiagnostics()
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [])

  return { diagnostics, status }
}
