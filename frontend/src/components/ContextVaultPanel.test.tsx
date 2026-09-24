import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ContextVaultPanel } from './ContextVaultPanel'
import { API_ENDPOINTS } from '../lib/api'
import { BASE_SETTINGS, buildSettingsResponse } from '../test/settingsFixtures'
import type { ContextVaultStatus } from '../types/context'
import type { ContextVaultSettings } from '../types/settings'

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

const INITIAL_STATUS: ContextVaultStatus = {
  enabled: false,
  destination_configured: true,
  export_restricted: false,
  restriction_code: null,
  dirty: false,
  refreshing: false,
  knowledge_revision: 11,
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

const ENTITY = { id: 'entity-project-atlas', name: 'Project Atlas', aliases: [], merged_into_entity_id: null }
const PREVIEW_RECORD = {
  record_id: 'record-atlas',
  kind: 'decision',
  text: 'Use a local-first launch plan.',
  status: 'active',
  sensitive: false,
  subject_entity_id: ENTITY.id,
  predicate: 'launch_plan',
  object_entity_id: null,
  object_value: 'local-first',
  eligible: true,
  exclusion_reasons: [],
  projected_path: 'records/record-atlas.md',
}

function mountVault(initial: ContextVaultSettings) {
  let currentSettings = initial
  let currentStatus = { ...INITIAL_STATUS, enabled: initial.enabled }
  const patches: Array<{ context_vault: ContextVaultSettings }> = []
  const previews: Array<{ candidate_scope: Record<string, unknown> }> = []
  const methods: string[] = []

  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    methods.push(method)
    if (url === API_ENDPOINTS.settings && method === 'GET') {
      return response(buildSettingsResponse({ ...BASE_SETTINGS, context_vault: currentSettings }))
    }
    if (url === API_ENDPOINTS.settings && method === 'PATCH') {
      const patch = JSON.parse(String(init?.body)) as { context_vault: ContextVaultSettings }
      patches.push(patch)
      currentSettings = patch.context_vault
      currentStatus = { ...currentStatus, enabled: currentSettings.enabled }
      return response(buildSettingsResponse({ ...BASE_SETTINGS, context_vault: currentSettings }))
    }
    if (url === API_ENDPOINTS.cortexVault) return response(currentStatus)
    if (url === API_ENDPOINTS.cortexVaultPreview && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as { candidate_scope: Record<string, unknown> }
      previews.push(body)
      const scope = body.candidate_scope
      return response({
        scope_id: scope.id,
        scope_name: scope.name,
        vault_enabled: currentSettings.enabled,
        scope_enabled: scope.enabled,
        hypothetical_enabled: true,
        destination_configured: true,
        export_restricted: false,
        restriction_code: null,
        candidate_count: 1,
        eligible_count: 1,
        records: [{ ...PREVIEW_RECORD, sensitive: scope.include_sensitive === true }],
        selection_issues: [],
      })
    }
    if (url.startsWith(`${API_ENDPOINTS.cortexContextEntities}?`)) return response([ENTITY])
    if (url.startsWith(`${API_ENDPOINTS.cortexContext}?`)) return response([])
    if (url === API_ENDPOINTS.cortexVaultCopies && method === 'DELETE') {
      currentStatus = { ...currentStatus, owned_file_count: 0, removed_file_count: 2 }
      return response(currentStatus)
    }
    throw new Error(`Unexpected request: ${method} ${url}`)
  })

  return { patches, previews, methods, status: () => currentStatus }
}

describe('ContextVaultPanel', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('requires a server preview after changing entity selection or sensitive opt-in', async () => {
    const requests = mountVault({ enabled: false, scopes: [] })
    render(<ContextVaultPanel demoModeActive={false} />)
    await screen.findByText('Export disabled')

    fireEvent.click(screen.getByRole('button', { name: 'Create scope' }))
    expect(screen.getByRole('button', { name: 'Preview draft' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Scope name'), { target: { value: 'Project Atlas' } })
    fireEvent.click(screen.getByLabelText('Enable this scope'))
    fireEvent.change(screen.getByLabelText('Search entities'), { target: { value: 'Atlas' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search entities' }))
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Project Atlas' }))

    expect(screen.getByRole('button', { name: 'Save scope settings' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Preview draft' }))
    expect(await screen.findByText(/1 of 1 records eligible/)).toBeInTheDocument()
    expect(requests.previews[0].candidate_scope).toEqual(expect.objectContaining({
      selected_entity_ids: [ENTITY.id],
      include_sensitive: false,
      enabled: true,
    }))

    fireEvent.click(screen.getByLabelText('Include sensitive records'))
    expect(screen.getByRole('button', { name: 'Save scope settings' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Preview draft' }))
    await waitFor(() => expect(requests.previews).toHaveLength(2))
    expect(requests.previews[1].candidate_scope.include_sensitive).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Save scope settings' }))

    await waitFor(() => expect(requests.patches).toHaveLength(1))
    expect(requests.patches[0].context_vault.enabled).toBe(false)
    expect(requests.patches[0].context_vault.scopes[0]).toEqual(expect.objectContaining({
      name: 'Project Atlas',
      enabled: true,
      selected_entity_ids: [ENTITY.id],
      include_sensitive: true,
    }))
    expect(screen.getByText(/Saving an enabled scope with selected entities authorizes future qualifying records/)).toBeInTheDocument()
  })

  it('keeps disabling export separate from removing generated copies', async () => {
    const scope: ContextVaultSettings['scopes'][number] = {
      id: 'scope-atlas',
      name: 'Project Atlas',
      enabled: true,
      selected_entity_ids: [ENTITY.id],
      record_ids: [],
      excluded_record_ids: [],
      include_sensitive: false,
    }
    const requests = mountVault({ enabled: true, scopes: [scope] })
    requests.status().owned_file_count = 2
    render(<ContextVaultPanel demoModeActive={false} />)
    await screen.findByText('Export enabled')

    expect(screen.getByRole('button', { name: 'Disable export' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove generated copies' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Disable export' }))
    await waitFor(() => expect(requests.patches).toHaveLength(1))
    expect(requests.patches[0].context_vault.enabled).toBe(false)
    expect(screen.getByText(/Existing generated files remain/)).toBeInTheDocument()
    expect(screen.getByText(/cannot recall information already copied/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove generated copies' }))
    await waitFor(() => expect(requests.methods).toContain('DELETE'))
  })

  it('keeps explicit record include and exclude removal controls visible after search results change', async () => {
    const includeId = 'record-included-outside-search'
    const excludeId = 'record-excluded-outside-search'
    const scope: ContextVaultSettings['scopes'][number] = {
      id: 'scope-atlas',
      name: 'Project Atlas',
      enabled: false,
      selected_entity_ids: [],
      record_ids: [includeId],
      excluded_record_ids: [excludeId],
      include_sensitive: false,
    }
    mountVault({ enabled: false, scopes: [scope] })
    render(<ContextVaultPanel demoModeActive={false} />)
    await screen.findByText('Export disabled')

    expect(screen.getByText(`Included: ${includeId}`)).toBeInTheDocument()
    expect(screen.getByText(`Excluded: ${excludeId}`)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: `Remove explicit record ${includeId}` }))
    fireEvent.click(screen.getByRole('button', { name: `Remove exclusion ${excludeId}` }))

    expect(screen.queryByText(`Included: ${includeId}`)).not.toBeInTheDocument()
    expect(screen.queryByText(`Excluded: ${excludeId}`)).not.toBeInTheDocument()
  })

  it('allows read-only preview in demo mode while keeping all export writes disabled', async () => {
    const scope: ContextVaultSettings['scopes'][number] = {
      id: 'scope-atlas',
      name: 'Project Atlas',
      enabled: true,
      selected_entity_ids: [ENTITY.id],
      record_ids: [],
      excluded_record_ids: [],
      include_sensitive: false,
    }
    const requests = mountVault({ enabled: false, scopes: [scope] })
    render(<ContextVaultPanel demoModeActive />)
    await screen.findByText('Export disabled')

    const previewButton = screen.getByRole('button', { name: 'Preview draft' })
    expect(previewButton).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Preview before enabling' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save scope settings' })).toBeDisabled()
    fireEvent.click(previewButton)

    expect(await screen.findByText(/1 of 1 records eligible/)).toBeInTheDocument()
    expect(requests.previews).toHaveLength(1)
    expect(requests.patches).toHaveLength(0)
  })
})
