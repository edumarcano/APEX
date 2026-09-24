import { useMemo, useState, type ReactElement } from 'react'

import { useContextVault } from '../hooks/useContextVault'
import type { ContextVaultPreview, ContextVaultStatus } from '../types/context'
import type { ContextVaultScopeSettings, ContextVaultSettings } from '../types/settings'

const buttonClass = 'rounded border border-white/10 px-2 py-1 text-xs text-[#7EB3FF] hover:border-white/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45'
const inputClass = 'w-full rounded border border-white/10 bg-zinc-950 p-2 text-xs text-zinc-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF]'

function copyScope(scope: ContextVaultScopeSettings): ContextVaultScopeSettings {
  return {
    ...scope,
    selected_entity_ids: [...scope.selected_entity_ids],
    record_ids: [...scope.record_ids],
    excluded_record_ids: [...scope.excluded_record_ids],
  }
}

function newScopeId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (digit) => {
    const value = Math.floor(Math.random() * 16)
    return (digit === 'x' ? value : (value & 0x3) | 0x8).toString(16)
  })
}

function selectionSignature(scope: ContextVaultScopeSettings | null): string {
  if (!scope) return ''
  return JSON.stringify({
    id: scope.id,
    selected_entity_ids: [...scope.selected_entity_ids].sort(),
    record_ids: [...scope.record_ids].sort(),
    excluded_record_ids: [...scope.excluded_record_ids].sort(),
    include_sensitive: scope.include_sensitive,
  })
}

function sameSelection(left: ContextVaultScopeSettings, right: ContextVaultScopeSettings): boolean {
  return selectionSignature(left) === selectionSignature(right)
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Not yet completed'
}

function statusFailureHelp(status: ContextVaultStatus): string | null {
  if (status.last_error_code === 'destination_unavailable') {
    return 'Check that the configured folder is available, then use Refresh now.'
  }
  if (status.last_error_code === 'unsafe_path') {
    return 'Choose a destination that does not overlap protected APEX data or escape the selected folder.'
  }
  if (status.last_error_code === 'publication_failed') {
    return 'Check the destination and its available space, then use Refresh now to retry.'
  }
  if (status.last_error_code === 'state_unavailable') {
    return 'Local export state could not be read. Check APEX storage access, then retry.'
  }
  return status.last_error_code ? 'Review the destination and use Refresh now to retry.' : null
}

function restrictionText(code: string | null): string {
  return code === 'demo_mode'
    ? 'Export changes are disabled in demo mode.'
    : 'Export changes are disabled while Cortex is using sandbox context.'
}

function PreviewResults({ preview }: { preview: ContextVaultPreview }): ReactElement {
  return (
    <section aria-label="Vault preview" className="space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">
          Draft preview · {preview.eligible_count} of {preview.candidate_count} records eligible
        </p>
        {preview.hypothetical_enabled ? (
          <span className="text-[10px] text-amber-200">Evaluated as enabled</span>
        ) : null}
      </div>
      {preview.export_restricted ? (
        <p role="status" className="text-xs text-amber-200">{restrictionText(preview.restriction_code)} Vault changes are read-only in this session.</p>
      ) : null}
      {!preview.destination_configured ? (
        <p className="text-xs text-amber-200">No destination folder is configured. Set APEX_CONTEXT_VAULT_PATH before enabling export.</p>
      ) : null}
      {preview.selection_issues.map((issue) => (
        <p key={issue.entity_id} className="text-xs text-amber-200">
          Entity {issue.entity_id} needs reselection{issue.replacement_entity_id ? `; its current entity is ${issue.replacement_entity_id}` : ''}.
        </p>
      ))}
      {!preview.records.length ? (
        <p className="text-xs text-zinc-500">This scope has no matching records yet. Selected entities can add future qualifying records.</p>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto" aria-label="Preview records">
          {preview.records.map((record) => (
            <li key={record.record_id} className="rounded border border-white/5 p-2 text-xs">
              <p className="text-zinc-200">{record.text}</p>
              <p className="mt-1 text-[10px] text-zinc-500">
                {record.kind} · {record.projected_path} · {record.eligible ? 'Will be exported' : `Excluded: ${record.exclusion_reasons.join(', ')}`}
                {record.sensitive ? ' · Sensitive' : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ContextVaultPanel({ demoModeActive }: { demoModeActive: boolean }): ReactElement {
  const vault = useContextVault()
  const settings = vault.settings
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null)
  const [scopeDraftOverride, setScopeDraftOverride] = useState<ContextVaultScopeSettings | null>(null)
  const [entityQuery, setEntityQuery] = useState('')
  const [recordQuery, setRecordQuery] = useState('')
  const [previewSignature, setPreviewSignature] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const scopeId = selectedScopeId ?? settings?.scopes[0]?.id ?? null
  const savedScope = useMemo(
    () => settings?.scopes.find((scope) => scope.id === scopeId) ?? null,
    [scopeId, settings],
  )
  const scopeDraft = useMemo(() => {
    if (scopeDraftOverride?.id === scopeId) return scopeDraftOverride
    return savedScope ? copyScope(savedScope) : null
  }, [savedScope, scopeDraftOverride, scopeId])
  const currentSignature = selectionSignature(scopeDraft)
  const previewIsCurrent = Boolean(previewSignature && previewSignature === currentSignature)
  const restricted = demoModeActive || Boolean(vault.status?.export_restricted)
  const enableableScopeExists = Boolean(scopeDraft?.enabled)
  const requiresPreview = Boolean(scopeDraft && (
    !savedScope ||
    !sameSelection(savedScope, scopeDraft) ||
    (!savedScope.enabled && scopeDraft.enabled)
  ))

  const updateScope = (update: (scope: ContextVaultScopeSettings) => ContextVaultScopeSettings): void => {
    setScopeDraftOverride((current) => {
      const source = current?.id === scopeId ? current : savedScope ? copyScope(savedScope) : null
      return source ? update(source) : null
    })
    setNotice(null)
  }

  const toggleId = (field: 'selected_entity_ids' | 'record_ids' | 'excluded_record_ids', id: string): void => {
    setPreviewSignature('')
    updateScope((scope) => {
      const values = scope[field]
      return {
        ...scope,
        [field]: values.includes(id) ? values.filter((item) => item !== id) : [...values, id],
      }
    })
  }

  const createScope = (): void => {
    const id = newScopeId()
    const next: ContextVaultScopeSettings = {
      id,
      name: '',
      enabled: false,
      selected_entity_ids: [],
      record_ids: [],
      excluded_record_ids: [],
      include_sensitive: false,
    }
    setSelectedScopeId(id)
    setScopeDraftOverride(next)
    setPreviewSignature('')
    setNotice(null)
  }

  const runPreview = async (): Promise<void> => {
    if (!scopeDraft || !scopeDraft.name.trim()) return
    const signature = selectionSignature(scopeDraft)
    const ok = await vault.requestPreview({ ...scopeDraft, enabled: true })
    if (ok) {
      setPreviewSignature(signature)
      setNotice('Preview loaded. Review eligible records and exclusions before saving.')
    }
  }

  const commitScope = async (enableVault = false): Promise<boolean> => {
    if (!settings || !scopeDraft) return false
    if (!scopeDraft.name.trim()) {
      setNotice('Enter a scope name before previewing or enabling export.')
      return false
    }
    if (requiresPreview && !previewIsCurrent) {
      setNotice('Preview this scope after its latest selection change before saving.')
      return false
    }
    if (enableVault && (!scopeDraft.enabled || !enableableScopeExists)) {
      setNotice('Enable at least one scope before enabling export.')
      return false
    }
    if (enableVault && !vault.status?.destination_configured) {
      setNotice('Configure APEX_CONTEXT_VAULT_PATH before enabling export.')
      return false
    }
    const scopes = settings.scopes.some((scope) => scope.id === scopeDraft.id)
      ? settings.scopes.map((scope) => scope.id === scopeDraft.id ? copyScope(scopeDraft) : copyScope(scope))
      : [...settings.scopes.map(copyScope), copyScope(scopeDraft)]
    const next: ContextVaultSettings = {
      enabled: enableVault || settings.enabled,
      scopes,
    }
    const ok = await vault.saveSettings(next)
    if (ok) {
      setScopeDraftOverride(null)
      setPreviewSignature('')
      setNotice(enableVault ? 'Export enabled for the previewed scope.' : 'Scope settings saved.')
      return true
    }
    return false
  }

  const disableExport = async (): Promise<void> => {
    if (!settings) return
    const ok = await vault.saveSettings({ ...settings, enabled: false })
    if (ok) {
      setNotice('Export disabled. Existing generated files remain in place.')
    }
  }

  const enableExport = async (): Promise<void> => {
    if (!settings || restricted) return
    if (!previewIsCurrent) {
      await runPreview()
      return
    }
    await commitScope(true)
  }

  const deleteScope = async (): Promise<void> => {
    if (!settings || !scopeDraft || !savedScope || restricted) return
    const next: ContextVaultSettings = {
      ...settings,
      scopes: settings.scopes.filter((scope) => scope.id !== scopeDraft.id),
    }
    if (await vault.saveSettings(next)) {
      setSelectedScopeId(next.scopes[0]?.id ?? null)
      setScopeDraftOverride(null)
      setPreviewSignature('')
      setNotice('Scope removed. Its generated notes will be removed on the next local refresh when export is enabled.')
    }
  }

  const refreshNow = async (): Promise<void> => {
    if (await vault.refreshNow()) setNotice('Local export refresh completed.')
  }

  const reloadSettings = async (): Promise<void> => {
    if (!await vault.reloadSettings()) return
    setSelectedScopeId(null)
    setScopeDraftOverride(null)
    setPreviewSignature('')
    setNotice('Current saved settings loaded; the previous draft was discarded.')
  }

  if (vault.loadState === 'loading') {
    return <div role="tabpanel" id="context-vault-panel" aria-labelledby="context-vault-tab" className="text-xs text-zinc-500">Loading vault settings and local export status…</div>
  }
  if (vault.loadState === 'error' || !settings) {
    return (
      <div role="tabpanel" id="context-vault-panel" aria-labelledby="context-vault-tab" className="space-y-2">
        <p role="alert" className="text-xs text-red-200">{vault.error ?? 'Context vault is unavailable.'}</p>
        <button type="button" className={buttonClass} onClick={() => void vault.load()}>Retry loading</button>
      </div>
    )
  }

  const status = vault.status
  const selectedEntityById = new Map(vault.entities.map((entity) => [entity.id, entity]))
  const savedScopeStatus = status?.scopes.find((scope) => scope.id === scopeDraft?.id)
  const activationBlocked = restricted || vault.settingsStale || !status?.destination_configured || !enableableScopeExists || !scopeDraft?.name.trim() || vault.isSaving

  return (
    <div id="context-vault-panel" role="tabpanel" aria-labelledby="context-vault-tab" className="space-y-3">
      <section aria-label="Vault status" className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">APEX Context vault</p>
            <p className="text-xs text-zinc-200">{settings.enabled ? 'Export enabled' : 'Export disabled'}</p>
          </div>
          {settings.enabled ? (
            <button type="button" className={buttonClass} disabled={restricted || vault.settingsStale || vault.isSaving} onClick={() => void disableExport()}>
              Disable export
            </button>
          ) : (
            <button type="button" className={buttonClass} disabled={activationBlocked} onClick={() => void enableExport()}>
              {previewIsCurrent ? 'Enable export' : 'Preview before enabling'}
            </button>
          )}
        </div>
        <dl className="grid grid-cols-1 gap-1 text-[11px] text-zinc-400 sm:grid-cols-2">
          <div><dt>Destination</dt><dd className="break-all text-zinc-200">{status?.destination_path ?? (status?.destination_configured ? 'Configured' : 'Not configured')}</dd></div>
          <div><dt>Generated files</dt><dd className="text-zinc-200">{status?.owned_file_count ?? 0} owned · {status?.changed_file_count ?? 0} changed · {status?.removed_file_count ?? 0} removed</dd></div>
          <div><dt>Local export state</dt><dd className="text-zinc-200">{status?.refreshing ? 'Refreshing' : status?.dirty ? 'Pending changes' : settings.enabled ? 'Current' : 'Paused'}</dd></div>
          <div><dt>Last successful refresh</dt><dd className="text-zinc-200">{formatTime(status?.last_success_at ?? null)}</dd></div>
          <div><dt>Last attempt</dt><dd className="text-zinc-200">{formatTime(status?.last_attempt_at ?? null)}</dd></div>
          <div><dt>Revision</dt><dd className="text-zinc-200">{status?.exported_revision ?? 'Not exported'} / {status?.knowledge_revision ?? 'Unknown'}</dd></div>
        </dl>
        {!status?.destination_configured ? <p className="text-xs text-amber-200">Set APEX_CONTEXT_VAULT_PATH to a local destination before enabling export.</p> : null}
        {status?.retained_destinations.length ? <p className="text-xs text-amber-200">Copies remain at an older destination: {status.retained_destinations.join(', ')}.</p> : null}
        {status?.export_restricted || demoModeActive ? <p role="status" className="text-xs text-amber-200">{restrictionText(status?.restriction_code ?? (demoModeActive ? 'demo_mode' : null))} Vault changes are read-only in this session.</p> : null}
        {status?.last_error_code ? <div role="alert" className="space-y-1 text-xs text-red-200"><p>Last export failed: {status.last_error_code.replaceAll('_', ' ')}.</p><p>{statusFailureHelp(status)}</p></div> : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} disabled={restricted || !settings.enabled || !status?.destination_configured || vault.isRefreshing || status.refreshing} onClick={() => void refreshNow()}>
            {vault.isRefreshing || status?.refreshing ? 'Refreshing…' : 'Refresh now'}
          </button>
          <button type="button" className={buttonClass} disabled={restricted || settings.enabled || !status?.owned_file_count || vault.isRemoving} onClick={() => void vault.removeCopies()}>
            {vault.isRemoving ? 'Removing…' : 'Remove generated copies'}
          </button>
        </div>
        <p className="text-[11px] text-zinc-500">Disabling export stops updates and keeps current generated files. Removing them deletes only APEX-managed local copies; it cannot recall information already copied, indexed, or retained elsewhere.</p>
      </section>

      {vault.settingsStale ? (
        <div role="alert" className="space-y-2 rounded border border-amber-400/30 p-3 text-xs text-amber-100">
          <p>{vault.error}</p>
          <p>Your unsaved draft is still here. Reloading will replace it with the latest saved scope list.</p>
          <button type="button" className={buttonClass} disabled={vault.isSaving} onClick={() => void reloadSettings()}>Reload current settings</button>
        </div>
      ) : null}
      {!vault.settingsStale && vault.error ? <p role="alert" className="text-xs text-red-200">{vault.error}</p> : null}

      <section className="space-y-3 rounded-lg border border-white/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-2 text-xs text-zinc-200">
            <span className="shrink-0">Scope</span>
            <select
              aria-label="Vault scope"
              className={`${inputClass} min-w-0`}
              disabled={vault.settingsStale}
              value={scopeId ?? ''}
              onChange={(event) => {
                setSelectedScopeId(event.target.value || null)
                setScopeDraftOverride(null)
                setPreviewSignature('')
                setNotice(null)
              }}
            >
              <option value="">Select a scope</option>
              {scopeDraft && !settings.scopes.some((scope) => scope.id === scopeDraft.id) ? <option value={scopeDraft.id}>{scopeDraft.name ? `New: ${scopeDraft.name}` : 'New scope'}</option> : null}
              {settings.scopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.name}</option>)}
            </select>
          </label>
          <button type="button" className={buttonClass} disabled={restricted || vault.settingsStale || vault.isSaving} onClick={createScope}>Create scope</button>
        </div>

        {scopeDraft ? (
          <>
            <label className="block space-y-1 text-xs text-zinc-400">
              <span>Scope name</span>
              <input aria-label="Scope name" className={inputClass} maxLength={80} value={scopeDraft.name} disabled={restricted} onChange={(event) => updateScope((scope) => ({ ...scope, name: event.target.value }))} />
            </label>
            {savedScopeStatus ? <p className="text-[11px] text-zinc-500">Saved selection: {savedScopeStatus.selected_entity_count} entities · {savedScopeStatus.record_count} direct records · {savedScopeStatus.excluded_record_count} exclusions · sensitive opt-in {savedScopeStatus.include_sensitive ? 'on' : 'off'}.</p> : null}
            <label className="flex items-center gap-2 text-xs text-zinc-300">
              <input aria-label="Enable this scope" type="checkbox" checked={scopeDraft.enabled} disabled={restricted} onChange={(event) => updateScope((scope) => ({ ...scope, enabled: event.target.checked }))} />
              Enable this scope
            </label>

            <section className="space-y-2 border-t border-white/10 pt-3">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">Selected entities</h3>
              <div className="flex gap-2">
                <input aria-label="Search entities" className={inputClass} value={entityQuery} onChange={(event) => setEntityQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void vault.searchEntities(entityQuery) } }} />
                <button type="button" className={buttonClass} onClick={() => void vault.searchEntities(entityQuery)}>Search entities</button>
              </div>
              <p className="text-[11px] text-zinc-500">Entity selection includes records where that entity is the subject or object. It does not follow neighboring entities.</p>
              <ul className="space-y-1">
                {scopeDraft.selected_entity_ids.map((id) => (
                  <li key={id} className="flex items-center justify-between gap-2 text-xs text-zinc-300">
                    <span>{selectedEntityById.get(id)?.name ?? id}</span>
                    <button type="button" className="text-red-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF]" aria-label={`Remove entity ${selectedEntityById.get(id)?.name ?? id}`} onClick={() => toggleId('selected_entity_ids', id)}>Remove</button>
                  </li>
                ))}
              </ul>
              {!vault.entities.length ? <p className="text-xs text-zinc-500">Search by entity name to select a project or person.</p> : null}
              <ul className="space-y-1">
                {vault.entities.map((entity) => (
                  <li key={entity.id}>
                    <label className="flex items-center gap-2 text-xs text-zinc-300">
                      <input type="checkbox" checked={scopeDraft.selected_entity_ids.includes(entity.id)} disabled={restricted} onChange={() => toggleId('selected_entity_ids', entity.id)} />
                      {entity.name}{entity.merged_into_entity_id ? ' · merged; reselect current entity' : ''}
                    </label>
                  </li>
                ))}
              </ul>
            </section>

            <section className="space-y-2 border-t border-white/10 pt-3">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">Explicit records</h3>
              <div className="flex gap-2">
                <input aria-label="Search records" className={inputClass} value={recordQuery} onChange={(event) => setRecordQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void vault.searchRecords(recordQuery) } }} />
                <button type="button" className={buttonClass} onClick={() => void vault.searchRecords(recordQuery)}>Search records</button>
              </div>
              <p className="text-[11px] text-zinc-500">Add individual records from outside selected entities, or exclude records that an entity selection would include. Exclusions always take precedence.</p>
              <ul aria-label="Selected explicit record controls" className="space-y-1">
                {scopeDraft.record_ids.map((id) => {
                  const record = vault.records.find((item) => item.id === id)
                  return (
                    <li key={`include-${id}`} className="flex items-center justify-between gap-2 rounded border border-white/5 p-2 text-xs text-zinc-300">
                      <span className="min-w-0 truncate">Included: {record?.text ?? id}</span>
                      <button type="button" className="shrink-0 text-red-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF]" aria-label={`Remove explicit record ${id}`} disabled={restricted} onClick={() => toggleId('record_ids', id)}>Remove</button>
                    </li>
                  )
                })}
                {scopeDraft.excluded_record_ids.map((id) => {
                  const record = vault.records.find((item) => item.id === id)
                  return (
                    <li key={`exclude-${id}`} className="flex items-center justify-between gap-2 rounded border border-white/5 p-2 text-xs text-zinc-300">
                      <span className="min-w-0 truncate">Excluded: {record?.text ?? id}</span>
                      <button type="button" className="shrink-0 text-red-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF]" aria-label={`Remove exclusion ${id}`} disabled={restricted} onClick={() => toggleId('excluded_record_ids', id)}>Remove</button>
                    </li>
                  )
                })}
              </ul>
              {vault.records.map((record) => (
                <div key={record.id} className="rounded border border-white/5 p-2 text-xs">
                  <p className="text-zinc-200">{record.text}</p>
                  <p className="mb-1 text-[10px] text-zinc-500">{record.kind} · {record.status}{record.sensitive ? ' · Sensitive' : ''}</p>
                  <div className="flex flex-wrap gap-3">
                    <label className="flex items-center gap-1 text-zinc-300">
                      <input type="checkbox" checked={scopeDraft.record_ids.includes(record.id)} disabled={restricted} onChange={() => toggleId('record_ids', record.id)} />
                      Include explicitly
                    </label>
                    <label className="flex items-center gap-1 text-zinc-300">
                      <input type="checkbox" checked={scopeDraft.excluded_record_ids.includes(record.id)} disabled={restricted} onChange={() => toggleId('excluded_record_ids', record.id)} />
                      Exclude from this scope
                    </label>
                  </div>
                </div>
              ))}
              {scopeDraft.record_ids.length || scopeDraft.excluded_record_ids.length ? (
                <p className="text-[11px] text-zinc-500">{scopeDraft.record_ids.length} explicit includes · {scopeDraft.excluded_record_ids.length} exclusions</p>
              ) : null}
            </section>

            <label className="flex items-start gap-2 border-t border-white/10 pt-3 text-xs text-zinc-300">
              <input aria-label="Include sensitive records" type="checkbox" checked={scopeDraft.include_sensitive} disabled={restricted} onChange={(event) => { setPreviewSignature(''); updateScope((scope) => ({ ...scope, include_sensitive: event.target.checked })) }} />
              <span><strong className="font-medium">Include sensitive records in this scope.</strong> This is a deliberate opt-in. Preview the exact eligible records before saving.</span>
            </label>

            <div className="flex flex-wrap gap-2">
              <button type="button" className={buttonClass} disabled={restricted || vault.settingsStale || !scopeDraft.name.trim() || vault.isPreviewing || vault.isSaving || (requiresPreview && !previewIsCurrent)} onClick={() => void commitScope()}>
                {vault.isSaving ? 'Saving…' : 'Save scope settings'}
              </button>
              <button type="button" className={buttonClass} disabled={!scopeDraft.name.trim() || vault.isPreviewing} onClick={() => void runPreview()}>
                {vault.isPreviewing ? 'Previewing…' : previewIsCurrent ? 'Refresh draft preview' : 'Preview draft'}
              </button>
              {savedScope ? <button type="button" className={buttonClass} disabled={restricted || vault.settingsStale || vault.isSaving} onClick={() => void deleteScope()}>Delete scope</button> : null}
            </div>
            {requiresPreview && !previewIsCurrent ? <p className="text-xs text-amber-200">Run a preview before saving this selection or enabling export. Selection changes invalidate earlier previews.</p> : null}
            <p className="text-xs text-amber-100">Saving an enabled scope with selected entities authorizes future qualifying records for those entities to be exported automatically. Preview shows current matches; future records cannot appear in today’s preview.</p>
            {notice ? <p role="status" className="text-xs text-emerald-200">{notice}</p> : null}
            {vault.preview && previewIsCurrent ? <PreviewResults preview={vault.preview} /> : null}
          </>
        ) : (
          <p className="text-xs text-zinc-500">No scope is configured. Create one to choose which accepted context can be exported.</p>
        )}
      </section>

      <section className="space-y-1 rounded-lg border border-white/10 p-3 text-xs text-zinc-400">
        <h3 className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">Sharing boundary</h3>
        <p>Each scope has its own folder and generated notes, so you can share scope folders separately. Sharing the vault root also shares its index and any other content accessible under that folder.</p>
        <p>APEX remains the source of truth. Export status reports local file publication; it does not confirm cloud sync or indexing by another application.</p>
      </section>
    </div>
  )
}
