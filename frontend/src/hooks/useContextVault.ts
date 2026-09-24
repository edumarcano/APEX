import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import {
  fetchContextVaultStatus,
  previewContextVault,
  refreshContextVault,
  removeContextVaultCopies,
  searchContextVaultEntities,
  searchContextVaultRecords,
} from '../lib/contextVault'
import {
  extractSettingsErrorDetail,
  parseSettingsResponse,
} from '../lib/settings'
import type {
  ContextEntity,
  ContextRecord,
  ContextVaultPreview,
  ContextVaultStatus,
} from '../types/context'
import type {
  ContextVaultScopeSettings,
  ContextVaultSettings,
} from '../types/settings'

export type ContextVaultLoadState = 'loading' | 'ready' | 'error'

function cloneSettings(settings: ContextVaultSettings): ContextVaultSettings {
  return {
    enabled: settings.enabled,
    scopes: settings.scopes.map((scope) => ({
      ...scope,
      selected_entity_ids: [...scope.selected_entity_ids],
      record_ids: [...scope.record_ids],
      excluded_record_ids: [...scope.excluded_record_ids],
    })),
  }
}

function canonicalSettings(settings: ContextVaultSettings): string {
  return JSON.stringify({
    enabled: settings.enabled,
    scopes: settings.scopes
      .map((scope) => ({
        id: scope.id,
        name: scope.name,
        enabled: scope.enabled,
        selected_entity_ids: [...scope.selected_entity_ids].sort(),
        record_ids: [...scope.record_ids].sort(),
        excluded_record_ids: [...scope.excluded_record_ids].sort(),
        include_sensitive: scope.include_sensitive,
      }))
      .sort((left, right) => left.id.localeCompare(right.id)),
  })
}

async function fetchSettings(): Promise<ContextVaultSettings> {
  const response = await fetch(API_ENDPOINTS.settings)
  if (!response.ok) throw new Error(await extractSettingsErrorDetail(response))
  const parsed = parseSettingsResponse(await response.json())
  if (!parsed) throw new Error('Settings response was malformed.')
  return cloneSettings(parsed.settings.context_vault)
}

export function useContextVault(enabled = true) {
  const [loadState, setLoadState] = useState<ContextVaultLoadState>(enabled ? 'loading' : 'ready')
  const [settings, setSettings] = useState<ContextVaultSettings | null>(null)
  const baseline = useRef<ContextVaultSettings | null>(null)
  const [status, setStatus] = useState<ContextVaultStatus | null>(null)
  const [preview, setPreview] = useState<ContextVaultPreview | null>(null)
  const [entities, setEntities] = useState<ContextEntity[]>([])
  const [records, setRecords] = useState<ContextRecord[]>([])
  const [settingsStale, setSettingsStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isRemoving, setIsRemoving] = useState(false)
  const requestId = useRef(0)
  const statusRequestId = useRef(0)
  const statusActionInFlight = useRef(false)

  const loadInitial = useCallback(async (request: number): Promise<void> => {
    try {
      const [nextSettings, nextStatus] = await Promise.all([
        fetchSettings(),
        fetchContextVaultStatus(),
      ])
      if (request !== requestId.current) return
      baseline.current = cloneSettings(nextSettings)
      setSettings(cloneSettings(nextSettings))
      setStatus(nextStatus)
      setPreview(null)
      setSettingsStale(false)
      setError(null)
      setLoadState('ready')
    } catch (cause) {
      if (request !== requestId.current) return
      setLoadState('error')
      setError(cause instanceof Error ? cause.message : 'Context vault settings could not be loaded.')
    }
  }, [])

  const load = useCallback(async (): Promise<void> => {
    if (!enabled) return
    const request = ++requestId.current
    setLoadState('loading')
    await loadInitial(request)
  }, [enabled, loadInitial])

  useEffect(() => {
    if (!enabled) return
    const request = ++requestId.current
    void loadInitial(request)
    return () => {
      if (request === requestId.current) requestId.current += 1
    }
  }, [enabled, loadInitial])

  const reloadSettings = useCallback(async (): Promise<boolean> => {
    setIsSaving(true)
    try {
      const [nextSettings, nextStatus] = await Promise.all([
        fetchSettings(),
        fetchContextVaultStatus(),
      ])
      const statusRequest = ++statusRequestId.current
      baseline.current = cloneSettings(nextSettings)
      setSettings(cloneSettings(nextSettings))
      if (statusRequest === statusRequestId.current) setStatus(nextStatus)
      setPreview(null)
      setSettingsStale(false)
      setError(null)
      setLoadState('ready')
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Current vault settings could not be reloaded.')
      return false
    } finally {
      setIsSaving(false)
    }
  }, [])

  const saveSettings = useCallback(async (nextSettings: ContextVaultSettings): Promise<boolean> => {
    const expected = baseline.current
    if (!expected || isSaving || settingsStale) return false
    setIsSaving(true)
    setError(null)
    try {
      const latest = await fetchSettings()
      if (canonicalSettings(latest) !== canonicalSettings(expected)) {
        setSettingsStale(true)
        setError('Vault settings changed elsewhere. Your draft is kept. Reload current settings before saving again.')
        return false
      }
      const response = await fetch(API_ENDPOINTS.settings, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context_vault: cloneSettings(nextSettings) }),
      })
      if (!response.ok) throw new Error(await extractSettingsErrorDetail(response))
      const parsed = parseSettingsResponse(await response.json())
      if (!parsed) throw new Error('Settings save response was malformed.')
      const saved = cloneSettings(parsed.settings.context_vault)
      baseline.current = cloneSettings(saved)
      setSettings(saved)
      setPreview(null)
      setSettingsStale(false)
      setError(null)
      const statusRequest = ++statusRequestId.current
      try {
        const nextStatus = await fetchContextVaultStatus()
        if (statusRequest === statusRequestId.current) setStatus(nextStatus)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Settings were saved, but export status could not be refreshed.')
      }
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Vault settings could not be saved.')
      return false
    } finally {
      setIsSaving(false)
    }
  }, [isSaving, settingsStale])

  const requestPreview = useCallback(async (scope: ContextVaultScopeSettings): Promise<boolean> => {
    if (isPreviewing) return false
    setIsPreviewing(true)
    setError(null)
    try {
      const next = await previewContextVault(scope)
      setPreview(next)
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Context vault preview could not be loaded.')
      setPreview(null)
      return false
    } finally {
      setIsPreviewing(false)
    }
  }, [isPreviewing])

  const refreshStatus = useCallback(async (): Promise<void> => {
    if (statusActionInFlight.current) return
    const request = ++statusRequestId.current
    try {
      const nextStatus = await fetchContextVaultStatus()
      if (request === statusRequestId.current && !statusActionInFlight.current) setStatus(nextStatus)
    } catch (cause) {
      if (request === statusRequestId.current && !statusActionInFlight.current) {
        setError(cause instanceof Error ? cause.message : 'Context vault status could not be refreshed.')
      }
    }
  }, [])

  const refreshNow = useCallback(async (): Promise<boolean> => {
    if (statusActionInFlight.current || isRefreshing || isRemoving) return false
    statusActionInFlight.current = true
    const request = ++statusRequestId.current
    setIsRefreshing(true)
    setError(null)
    try {
      const nextStatus = await refreshContextVault()
      if (request === statusRequestId.current) setStatus(nextStatus)
      if (nextStatus.last_error_code) {
        setError(`Vault refresh failed: ${nextStatus.last_error_code.replaceAll('_', ' ')}.`)
        return false
      }
      if (nextStatus.dirty || nextStatus.refreshing) {
        setError('Vault refresh is still pending. Status will update as the local export finishes.')
        return false
      }
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Context vault refresh failed.')
      try {
        const nextStatus = await fetchContextVaultStatus()
        if (request === statusRequestId.current) setStatus(nextStatus)
      } catch {
        // Preserve the refresh error when the follow-up status read also fails.
      }
      return false
    } finally {
      statusActionInFlight.current = false
      setIsRefreshing(false)
    }
  }, [isRefreshing, isRemoving])

  const removeCopies = useCallback(async (): Promise<boolean> => {
    if (statusActionInFlight.current || isRemoving || isRefreshing) return false
    statusActionInFlight.current = true
    const request = ++statusRequestId.current
    setIsRemoving(true)
    setError(null)
    try {
      const nextStatus = await removeContextVaultCopies()
      if (request === statusRequestId.current) setStatus(nextStatus)
      if (nextStatus.last_error_code || nextStatus.refreshing || nextStatus.owned_file_count > 0) {
        setError(nextStatus.last_error_code
          ? `Generated copies could not all be removed: ${nextStatus.last_error_code.replaceAll('_', ' ')}.`
          : 'Some generated copies remain. Review export status before trying again.')
        return false
      }
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Generated copies could not be removed.')
      try {
        const nextStatus = await fetchContextVaultStatus()
        if (request === statusRequestId.current) setStatus(nextStatus)
      } catch {
        // Preserve the removal error when the follow-up status read also fails.
      }
      return false
    } finally {
      statusActionInFlight.current = false
      setIsRemoving(false)
    }
  }, [isRefreshing, isRemoving])

  useEffect(() => {
    if (!enabled) return
    const interval = window.setInterval(() => { void refreshStatus() }, 5000)
    return () => window.clearInterval(interval)
  }, [enabled, refreshStatus])

  const searchEntities = useCallback(async (query: string): Promise<void> => {
    try {
      const matches = await searchContextVaultEntities(query)
      setEntities((current) => {
        const known = new Map(current.map((entity) => [entity.id, entity]))
        for (const entity of matches) known.set(entity.id, entity)
        return [...known.values()]
      })
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Entity search failed.')
    }
  }, [])

  const searchRecords = useCallback(async (query: string): Promise<void> => {
    try {
      setRecords(await searchContextVaultRecords(query))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Record search failed.')
    }
  }, [])

  return {
    loadState,
    settings,
    status,
    preview,
    entities,
    records,
    settingsStale,
    error,
    isPreviewing,
    isSaving,
    isRefreshing,
    isRemoving,
    load,
    reloadSettings,
    saveSettings,
    requestPreview,
    refreshNow,
    removeCopies,
    refreshStatus,
    searchEntities,
    searchRecords,
  }
}
