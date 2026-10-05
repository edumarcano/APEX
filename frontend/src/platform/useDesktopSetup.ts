import { useCallback, useEffect, useRef, useState } from 'react'

import type { DesktopPlatform, DesktopSetupState, ImportItem } from './contracts'

const SETUP_REFRESH_MS = 2_500
const EMPTY_SETUP: DesktopSetupState = {
  revision: -1,
  phase: 'checking',
  preview: null,
  progress: null,
  error_code: null,
}

export function useDesktopSetup(platform: DesktopPlatform): {
  setup: DesktopSetupState
  busy: boolean
  actionError: string | null
  chooseImport: () => Promise<void>
  freshStart: () => Promise<void>
  importData: () => Promise<void>
  recoverImport: () => Promise<void>
} {
  const [setup, setSetup] = useState(EMPTY_SETUP)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const latest = useRef(EMPTY_SETUP)
  const active = useRef(false)
  const refreshRef = useRef<(() => Promise<void>) | null>(null)
  const busyRef = useRef(false)

  useEffect(() => {
    let alive = true
    let inFlight = false
    let queued = false
    let unsubscribe: (() => void) | undefined
    let timer = 0
    active.current = true

    const refresh = async (): Promise<void> => {
      if (!alive) return
      if (inFlight) {
        queued = true
        return
      }
      inFlight = true
      try {
        do {
          queued = false
          try {
            const snapshot = await platform.getSetupStatus()
            if (alive) acceptSetupSnapshot(snapshot, latest, setSetup)
          } catch {
            if (alive && latest.current.revision < 0) {
              acceptSetupSnapshot({ ...EMPTY_SETUP, revision: 0, phase: 'failed', error_code: 'protocol_error' }, latest, setSetup)
            }
          }
        } while (alive && queued)
      } finally {
        inFlight = false
      }
    }
    refreshRef.current = refresh

    void (async () => {
      try {
        unsubscribe = await platform.subscribeSetupState(() => { void refresh() })
      } catch {
        // Status snapshots remain authoritative when wakeup subscription is unavailable.
      }
      if (!alive) {
        unsubscribe?.()
        return
      }
      void refresh()
      timer = window.setInterval(() => {
        if (latest.current.phase !== 'ready') void refresh()
      }, SETUP_REFRESH_MS)
    })()

    return () => {
      alive = false
      active.current = false
      refreshRef.current = null
      window.clearInterval(timer)
      unsubscribe?.()
    }
  }, [platform])

  const run = useCallback(async (operation: () => Promise<DesktopSetupState>): Promise<void> => {
    if (busyRef.current || !active.current) return
    busyRef.current = true
    setBusy(true)
    setActionError(null)
    try {
      const result = await operation()
      if (active.current) acceptSetupSnapshot(result, latest, setSetup)
    } catch {
      if (active.current) setActionError('The setup action could not be completed. Check the current setup status and try again.')
    } finally {
      if (active.current) {
        await refreshRef.current?.()
        busyRef.current = false
        setBusy(false)
      }
    }
  }, [])

  const chooseImport = useCallback(async (): Promise<void> => {
    if (busyRef.current || !active.current) return
    busyRef.current = true
    setBusy(true)
    setActionError(null)
    try {
      const sourceDir = await platform.pickImportSource()
      if (!sourceDir || !active.current) return
      const result = await platform.previewImport(sourceDir)
      if (active.current) acceptSetupSnapshot(result, latest, setSetup)
    } catch {
      if (active.current) setActionError('The source folder could not be previewed. Choose a folder and try again.')
    } finally {
      if (active.current) {
        await refreshRef.current?.()
        busyRef.current = false
        setBusy(false)
      }
    }
  }, [platform])

  const freshStart = useCallback(() => run(() => platform.freshStart()), [platform, run])
  const importData = useCallback(() => {
    const previewId = latest.current.preview?.preview_id
    if (!previewId || !latest.current.preview?.can_import) return Promise.resolve()
    return run(() => platform.importData(previewId))
  }, [platform, run])
  const recoverImport = useCallback(() => run(() => platform.recoverImport()), [platform, run])

  return { setup, busy, actionError, chooseImport, freshStart, importData, recoverImport }
}

function acceptSetupSnapshot(
  value: unknown,
  latest: { current: DesktopSetupState },
  setSetup: (next: DesktopSetupState) => void,
): void {
  if (!isDesktopSetupState(value)) {
    if (latest.current.phase === 'checking') {
      const failure = { ...EMPTY_SETUP, revision: Math.max(0, latest.current.revision + 1), phase: 'failed' as const, error_code: 'protocol_error' }
      latest.current = failure
      setSetup(failure)
    }
    return
  }
  if (value.revision <= latest.current.revision) return
  latest.current = value
  setSetup(value)
}

export function isDesktopSetupState(value: unknown): value is DesktopSetupState {
  if (!value || typeof value !== 'object') return false
  const state = value as Partial<DesktopSetupState>
  return Number.isSafeInteger(state.revision) && state.revision! >= 0 &&
    ['checking', 'choice_required', 'preview_ready', 'importing', 'ready', 'recovery_required', 'failed'].includes(state.phase ?? '') &&
    (state.preview === null || isImportPreview(state.preview)) &&
    (state.progress === null || Boolean(state.progress && typeof state.progress.stage === 'string' &&
      Number.isSafeInteger(state.progress.completed_bytes) && state.progress.completed_bytes >= 0 &&
      Number.isSafeInteger(state.progress.total_bytes) && state.progress.total_bytes >= 0)) &&
    (state.error_code === null || typeof state.error_code === 'string')
}

function isImportPreview(value: unknown): value is NonNullable<DesktopSetupState['preview']> {
  if (!value || typeof value !== 'object') return false
  const preview = value as Partial<NonNullable<DesktopSetupState['preview']>>
  return typeof preview.preview_id === 'string' && typeof preview.can_import === 'boolean' &&
    Array.isArray(preview.items) && preview.items.every(isImportItem) &&
    Array.isArray(preview.warnings) && preview.warnings.every((item) => typeof item === 'string') &&
    Array.isArray(preview.blockers) && preview.blockers.every((item) => typeof item === 'string')
}

function isImportItem(value: unknown): value is ImportItem {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ImportItem>
  return typeof item.path === 'string' && typeof item.category === 'string' &&
    ['copy', 'missing', 'retain_external', 'reuse'].includes(item.disposition ?? '') &&
    Number.isSafeInteger(item.file_count) && item.file_count! >= 0 &&
    Number.isSafeInteger(item.total_bytes) && item.total_bytes! >= 0
}
