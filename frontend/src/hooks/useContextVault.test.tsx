import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { API_ENDPOINTS } from '../lib/api'
import { BASE_SETTINGS, buildSettingsResponse } from '../test/settingsFixtures'
import type { ContextVaultStatus } from '../types/context'
import type { ContextVaultScopeSettings } from '../types/settings'
import { useContextVault } from './useContextVault'

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

const STATUS: ContextVaultStatus = {
  enabled: false,
  destination_configured: true,
  export_restricted: false,
  restriction_code: null,
  dirty: false,
  refreshing: false,
  knowledge_revision: 4,
  exported_revision: null,
  last_attempt_at: null,
  attempt_count: 0,
  last_success_at: null,
  owned_file_count: 0,
  changed_file_count: 0,
  removed_file_count: 0,
  last_error_code: null,
  destination_path: 'D:/APEX-Vault',
  retained_destinations: [],
  scopes: [],
}

const SCOPE: ContextVaultScopeSettings = {
  id: 'scope-1',
  name: 'Project Atlas',
  enabled: true,
  selected_entity_ids: ['entity-1'],
  record_ids: [],
  excluded_record_ids: [],
  include_sensitive: false,
}

function settingsWith(scopes: ContextVaultScopeSettings[] = [], enabled = false) {
  return buildSettingsResponse({
    ...BASE_SETTINGS,
    context_vault: { enabled, scopes },
  })
}

describe('useContextVault', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('previews a candidate scope through the server without saving it', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(settingsWith()))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response({
        scope_id: SCOPE.id,
        scope_name: SCOPE.name,
        vault_enabled: false,
        scope_enabled: true,
        hypothetical_enabled: true,
        destination_configured: true,
        export_restricted: false,
        restriction_code: null,
        candidate_count: 0,
        eligible_count: 0,
        records: [],
        selection_issues: [],
        projection_comparison_state: 'no_prior_export',
        projection_changes: [],
      }))
    const { result } = renderHook(() => useContextVault())
    await waitFor(() => expect(result.current.loadState).toBe('ready'))

    await act(async () => { await result.current.requestPreview(SCOPE) })

    expect(result.current.preview?.hypothetical_enabled).toBe(true)
    expect(result.current.settings?.scopes).toEqual([])
    expect(fetch).toHaveBeenLastCalledWith(API_ENDPOINTS.cortexVaultPreview, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ candidate_scope: SCOPE }),
    }))
  })

  it('detects changed saved vault settings before replacing the scope list and offers reload', async () => {
    const remoteScope = { ...SCOPE, id: 'scope-remote', name: 'Other project' }
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(settingsWith()))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response(settingsWith([remoteScope])))

    const { result } = renderHook(() => useContextVault())
    await waitFor(() => expect(result.current.loadState).toBe('ready'))

    let saved = true
    await act(async () => { saved = await result.current.saveSettings({ enabled: true, scopes: [SCOPE] }) })

    expect(saved).toBe(false)
    expect(result.current.settingsStale).toBe(true)
    expect(result.current.settings?.scopes).toEqual([])
    expect(result.current.error).toMatch(/changed elsewhere/)
    expect(fetch).not.toHaveBeenCalledWith(API_ENDPOINTS.settings, expect.objectContaining({ method: 'PATCH' }))

    vi.mocked(fetch)
      .mockResolvedValueOnce(response(settingsWith([remoteScope])))
      .mockResolvedValueOnce(response({ ...STATUS, scopes: [{
        id: remoteScope.id,
        name: remoteScope.name,
        enabled: false,
        selected_entity_count: 0,
        record_count: 0,
        excluded_record_count: 0,
        include_sensitive: false,
      }] }))
    await act(async () => { await result.current.reloadSettings() })

    expect(result.current.settingsStale).toBe(false)
    expect(result.current.settings?.scopes).toEqual([remoteScope])
  })

  it.each([
    ['pending', { ...STATUS, dirty: true }],
    ['failed', { ...STATUS, last_error_code: 'publication_failed' }],
  ])('does not report a %s HTTP 200 refresh as successful', async (_state, reportedStatus) => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(settingsWith()))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response(reportedStatus))
    const { result } = renderHook(() => useContextVault())
    await waitFor(() => expect(result.current.loadState).toBe('ready'))

    let success = true
    await act(async () => { success = await result.current.refreshNow() })

    expect(success).toBe(false)
    expect(result.current.status).toEqual(reportedStatus)
    expect(result.current.error).toMatch(reportedStatus.last_error_code ? /failed/ : /pending/)
  })

  it('keeps status polling from overwriting a newer manual refresh response', async () => {
    vi.useFakeTimers()
    let statusReads = 0
    let resolvePoll: ((value: Response) => void) | undefined
    const staleStatus = { ...STATUS, knowledge_revision: 2 }
    const freshStatus = { ...STATUS, knowledge_revision: 5, last_success_at: '2026-09-24T12:00:00Z' }
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = String(input)
      if (url === API_ENDPOINTS.settings) return Promise.resolve(response(settingsWith()))
      if (url === API_ENDPOINTS.cortexVault && !init?.method) {
        statusReads += 1
        if (statusReads === 1) return Promise.resolve(response(STATUS))
        return new Promise<Response>((resolve) => { resolvePoll = resolve })
      }
      if (url === API_ENDPOINTS.cortexVaultRefresh) return Promise.resolve(response(freshStatus))
      throw new Error(`Unexpected request: ${String(init?.method ?? 'GET')} ${url}`)
    })

    const { result, unmount } = renderHook(() => useContextVault())
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(result.current.loadState).toBe('ready')

    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(resolvePoll).toBeDefined()
    let refreshed = false
    await act(async () => { refreshed = await result.current.refreshNow() })
    expect(refreshed).toBe(true)

    await act(async () => { resolvePoll?.(response(staleStatus)); await Promise.resolve() })
    expect(result.current.status).toEqual(freshStatus)
    unmount()
  })

  it('reports incomplete copy removal when HTTP 200 still lists owned files', async () => {
    const remainingCopies = { ...STATUS, owned_file_count: 1 }
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(settingsWith()))
      .mockResolvedValueOnce(response(STATUS))
      .mockResolvedValueOnce(response(remainingCopies))
    const { result } = renderHook(() => useContextVault())
    await waitFor(() => expect(result.current.loadState).toBe('ready'))

    let removed = true
    await act(async () => { removed = await result.current.removeCopies() })

    expect(removed).toBe(false)
    expect(result.current.status?.owned_file_count).toBe(1)
    expect(result.current.error).toMatch(/remain/)
  })
})
