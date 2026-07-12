import { useCallback, useEffect, useMemo, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import {
  cloneRuntimeSettings,
  diffSettingsPatch,
  extractSettingsErrorDetail,
  isSettingsPatchEmpty,
  parseSettingsResponse,
  settingsAreEqual,
} from '../lib/settings'
import type { RuntimeSettings, SettingsResponse } from '../types/settings'

const SETTINGS_ENDPOINT = API_ENDPOINTS.settings

export type SettingsLoadStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface UseSettingsEditorOptions {
  open: boolean
  onApplied?: (response: SettingsResponse) => void
}

export interface UseSettingsEditorResult {
  loadStatus: SettingsLoadStatus
  loadError: string | null
  envelope: SettingsResponse | null
  baseline: RuntimeSettings | null
  draft: RuntimeSettings | null
  isDirty: boolean
  saving: boolean
  saveError: string | null
  setDraft: (updater: (prev: RuntimeSettings) => RuntimeSettings) => void
  save: () => Promise<boolean>
  resetDraft: () => void
}

export function useSettingsEditor({
  open,
  onApplied,
}: UseSettingsEditorOptions): UseSettingsEditorResult {
  const [loadStatus, setLoadStatus] = useState<SettingsLoadStatus>('idle')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [envelope, setEnvelope] = useState<SettingsResponse | null>(null)
  const [baseline, setBaseline] = useState<RuntimeSettings | null>(null)
  const [draft, setDraftState] = useState<RuntimeSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      return undefined
    }

    const controller = new AbortController()

    const load = async () => {
      setLoadStatus('loading')
      setLoadError(null)
      setSaveError(null)
      setEnvelope(null)
      setBaseline(null)
      setDraftState(null)

      try {
        const response = await fetch(SETTINGS_ENDPOINT, { signal: controller.signal })
        if (!response.ok) {
          throw new Error(await extractSettingsErrorDetail(response))
        }

        const body: unknown = await response.json()
        const parsed = parseSettingsResponse(body)
        if (!parsed) {
          throw new Error('Settings response was malformed.')
        }

        if (controller.signal.aborted) {
          return
        }

        setEnvelope(parsed)
        setBaseline(cloneRuntimeSettings(parsed.settings))
        setDraftState(cloneRuntimeSettings(parsed.settings))
        setLoadStatus('ready')
      } catch (error) {
        if (controller.signal.aborted) {
          return
        }
        const message =
          error instanceof Error ? error.message : 'Failed to load settings.'
        setLoadError(message)
        setLoadStatus('error')
        setEnvelope(null)
        setBaseline(null)
        setDraftState(null)
      }
    }

    void load()

    return () => {
      controller.abort()
    }
  }, [open])

  const isDirty = useMemo(() => {
    if (!baseline || !draft) {
      return false
    }
    return !settingsAreEqual(baseline, draft)
  }, [baseline, draft])

  const setDraft = useCallback((updater: (prev: RuntimeSettings) => RuntimeSettings) => {
    setDraftState((prev) => {
      if (!prev) {
        return prev
      }
      return updater(prev)
    })
    setSaveError(null)
  }, [])

  const resetDraft = useCallback(() => {
    if (!baseline) {
      return
    }
    setDraftState(cloneRuntimeSettings(baseline))
    setSaveError(null)
  }, [baseline])

  const save = useCallback(async (): Promise<boolean> => {
    if (!baseline || !draft || saving) {
      return false
    }

    const patch = diffSettingsPatch(baseline, draft)
    if (isSettingsPatchEmpty(patch)) {
      return true
    }

    setSaving(true)
    setSaveError(null)

    try {
      const response = await fetch(SETTINGS_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })

      if (!response.ok) {
        throw new Error(await extractSettingsErrorDetail(response))
      }

      const body: unknown = await response.json()
      const parsed = parseSettingsResponse(body)
      if (!parsed) {
        throw new Error('Settings save response was malformed.')
      }

      setEnvelope(parsed)
      setBaseline(cloneRuntimeSettings(parsed.settings))
      setDraftState(cloneRuntimeSettings(parsed.settings))
      onApplied?.(parsed)
      return true
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to save settings.'
      setSaveError(message)
      return false
    } finally {
      setSaving(false)
    }
  }, [baseline, draft, saving, onApplied])

  return {
    loadStatus,
    loadError,
    envelope,
    baseline,
    draft,
    isDirty,
    saving,
    saveError,
    setDraft,
    save,
    resetDraft,
  }
}
