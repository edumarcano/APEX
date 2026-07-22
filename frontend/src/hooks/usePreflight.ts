import { useCallback, useRef, useState } from 'react'

import type { PreflightBlocker, PreflightOperation, PreflightRequest, PreflightResponse, PreflightWarning } from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const PREFLIGHT_ENDPOINT = API_ENDPOINTS.preflight

export type PreflightResolution = 'proceed' | 'blocked' | 'cancelled'

export type PreflightDialogChoice = 'continue_once' | 'continue_session' | 'cancel'

export interface PreflightDialogProps {
  open: boolean
  operation: PreflightOperation | null
  warnings: PreflightWarning[]
  blockers: PreflightBlocker[]
  isChecking: boolean
  error: string | null
  onChoice: (choice: PreflightDialogChoice) => void
}

export type UsePreflightReturn = {
  dialogOpen: boolean
  pendingOperation: PreflightOperation | null
  warnings: PreflightWarning[]
  blockers: PreflightBlocker[]
  isChecking: boolean
  error: string | null
  requestOperation: (
    operation: PreflightOperation,
    options?: Pick<PreflightRequest, 'connectors' | 'briefing_mode' | 'synthesis_profile' | 'force' | 'involves_cloud'>,
  ) => Promise<PreflightResolution>
  resolveDialog: (choice: PreflightDialogChoice) => void
}

function parsePreflightResponse(body: unknown): PreflightResponse | null {
  if (!body || typeof body !== 'object') {
    return null
  }

  const record = body as Record<string, unknown>
  const warningsRaw = Array.isArray(record.warnings) ? record.warnings : []
  const blockersRaw = Array.isArray(record.blockers) ? record.blockers : []

  const warnings: PreflightWarning[] = warningsRaw
    .map((entry): PreflightWarning | null => {
      if (!entry || typeof entry !== 'object') return null
      const row = entry as Record<string, unknown>
      if (typeof row.code !== 'string' || typeof row.message !== 'string') return null
      return { code: row.code as PreflightWarning['code'], message: row.message }
    })
    .filter((entry): entry is PreflightWarning => entry !== null)

  const blockers: PreflightBlocker[] = blockersRaw
    .map((entry): PreflightBlocker | null => {
      if (!entry || typeof entry !== 'object') return null
      const row = entry as Record<string, unknown>
      if (typeof row.code !== 'string' || typeof row.message !== 'string') return null
      return { code: row.code as PreflightBlocker['code'], message: row.message }
    })
    .filter((entry): entry is PreflightBlocker => entry !== null)

  return {
    warnings,
    blockers,
    can_proceed: record.can_proceed === true,
  }
}

export function usePreflight(): UsePreflightReturn {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [pendingOperation, setPendingOperation] = useState<PreflightOperation | null>(null)
  const [warnings, setWarnings] = useState<PreflightWarning[]>([])
  const [blockers, setBlockers] = useState<PreflightBlocker[]>([])
  const [isChecking, setIsChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const acknowledgedWarningsRef = useRef<Set<string>>(new Set())
  const cloudDisclosureAcknowledgedRef = useRef(false)
  const resolverRef = useRef<((resolution: PreflightResolution) => void) | null>(null)
  const inFlightRef = useRef(false)

  const resolveDialog = useCallback((choice: PreflightDialogChoice): void => {
    const resolver = resolverRef.current
    resolverRef.current = null
    setDialogOpen(false)
    setPendingOperation(null)

    if (!resolver) {
      return
    }

    if (choice === 'cancel') {
      resolver('cancelled')
      return
    }

    if (choice === 'continue_session') {
      for (const warning of warnings) {
        acknowledgedWarningsRef.current.add(warning.code)
        if (warning.code === 'cloud_data_disclosure') {
          cloudDisclosureAcknowledgedRef.current = true
        }
      }
    }

    resolver('proceed')
  }, [warnings])

  const requestOperation = useCallback(
    async (
      operation: PreflightOperation,
      options: Pick<PreflightRequest, 'connectors' | 'briefing_mode' | 'synthesis_profile' | 'force' | 'involves_cloud'> = {},
    ): Promise<PreflightResolution> => {
      if (inFlightRef.current) {
        return 'blocked'
      }

      inFlightRef.current = true
      setIsChecking(true)
      setError(null)

      try {
        const response = await fetch(PREFLIGHT_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            operation,
            ...options,
            acknowledged_warnings: Array.from(acknowledgedWarningsRef.current),
            cloud_disclosure_acknowledged: cloudDisclosureAcknowledgedRef.current,
          } satisfies PreflightRequest),
        })

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          body = null
        }

        if (!response.ok) {
          const message =
            body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string'
              ? (body as { detail: string }).detail
              : `Preflight check failed with status ${response.status}`
          setError(message)
          return 'blocked'
        }

        const parsed = parsePreflightResponse(body)
        if (!parsed) {
          setError('Invalid preflight response')
          return 'blocked'
        }

        setIsChecking(false)
        setWarnings(parsed.warnings)
        setBlockers(parsed.blockers)

        if (parsed.blockers.length > 0 || !parsed.can_proceed) {
          setPendingOperation(operation)
          setDialogOpen(true)
          return await new Promise<PreflightResolution>((resolve) => {
            resolverRef.current = (resolution) => {
              resolve(resolution === 'proceed' ? 'blocked' : resolution)
            }
          })
        }

        if (parsed.warnings.length === 0) {
          return 'proceed'
        }

        setPendingOperation(operation)
        setDialogOpen(true)
        return await new Promise<PreflightResolution>((resolve) => {
          resolverRef.current = resolve
        })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown preflight error')
        return 'blocked'
      } finally {
        inFlightRef.current = false
        setIsChecking(false)
      }
    },
    [],
  )

  return {
    dialogOpen,
    pendingOperation,
    warnings,
    blockers,
    isChecking,
    error,
    requestOperation,
    resolveDialog,
  }
}
