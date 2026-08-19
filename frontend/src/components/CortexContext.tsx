import { Loader2 } from 'lucide-react'
import { useEffect, useState, type ReactElement } from 'react'

import type { useContextInspector } from '../hooks/useContextInspector'
import type { ContextCaptureInput, ContextKind, ContextRecord } from '../types/context'

type Inspector = ReturnType<typeof useContextInspector>

const KINDS: ContextKind[] = ['idea', 'preference', 'decision', 'goal', 'fact', 'constraint', 'note', 'observation']
const STATUSES = ['active', 'conflicting', 'superseded', 'retracted'] as const

function statusClass(status: string): string {
  if (status === 'active') return 'text-emerald-200'
  if (status === 'conflicting') return 'text-amber-200'
  if (status === 'retracted') return 'text-red-200'
  return 'text-zinc-500'
}

function CaptureForm({ label, onSubmit, disabled }: { label: string; onSubmit: (value: ContextCaptureInput) => Promise<boolean>; disabled: boolean }): ReactElement {
  const [kind, setKind] = useState<ContextKind>('note')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (): Promise<void> => {
    if (!text.trim() || saving) return
    setSaving(true)
    const accepted = await onSubmit({ kind, text: text.trim() })
    if (accepted) setText('')
    setSaving(false)
  }
  return <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-3">
    <p className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
    <select aria-label={`${label} kind`} value={kind} disabled={disabled || saving} onChange={(event) => setKind(event.target.value as ContextKind)} className="w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-200">
      {KINDS.map((item) => <option key={item} value={item}>{item}</option>)}
    </select>
    <textarea aria-label={`${label} text`} value={text} disabled={disabled || saving} onChange={(event) => setText(event.target.value)} rows={3} maxLength={10000} className="w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-200" />
    <button type="button" disabled={disabled || saving || !text.trim()} onClick={() => void submit()} className="rounded border border-[#7EB3FF]/45 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white disabled:opacity-45">{saving ? 'Proposing…' : 'Propose action'}</button>
  </div>
}

function RecordRow({ record, selected, onSelect }: { record: ContextRecord; selected: boolean; onSelect: () => void }): ReactElement {
  return <button type="button" onClick={onSelect} className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${selected ? 'border-[#7EB3FF]/45 bg-[#0F4DB8]/15' : 'border-white/5 bg-white/[0.02] hover:border-white/15'}`}>
    <span className="flex items-center justify-between gap-2 font-mono text-[10px] uppercase tracking-wide"><span className="text-zinc-400">{record.kind}</span><span className={statusClass(record.status)}>{record.status}</span></span>
    <span className="mt-1 block line-clamp-2 text-xs leading-relaxed text-zinc-200">{record.text}</span>
  </button>
}

export function CortexContext({ inspector, demoModeActive }: { inspector: Inspector; demoModeActive: boolean }): ReactElement {
  const [showCapture, setShowCapture] = useState(false)
  const [showCorrection, setShowCorrection] = useState(false)
  const [alias, setAlias] = useState('')
  const [mergeTargetId, setMergeTargetId] = useState('')
  const detail = inspector.detail
  const searchEntities = inspector.searchEntities
  useEffect(() => { queueMicrotask(() => void searchEntities()) }, [searchEntities])
  const changeStatuses = (status: typeof STATUSES[number]): void => inspector.setFilters((current) => ({ ...current, statuses: current.statuses.includes(status) ? current.statuses.filter((item) => item !== status) : [...current.statuses, status] }))
  const proposeAndRefresh = async (operation: Parameters<typeof inspector.reconcile>[0]): Promise<void> => {
    if (await inspector.reconcile(operation)) await inspector.refresh()
  }
  const subject = detail?.subject ?? detail?.object_entity ?? null
  return <section className="space-y-3" aria-label="Personal context">
    <div className="flex items-center justify-between gap-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Personal context</p><button type="button" onClick={() => setShowCapture((value) => !value)} disabled={demoModeActive} className="font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white disabled:opacity-45">{showCapture ? 'Close' : 'Capture'}</button></div>
    {demoModeActive ? <p className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-[11px] text-zinc-500">Context changes are unavailable in demo mode.</p> : null}
    {showCapture ? <CaptureForm label="Manual capture" disabled={demoModeActive} onSubmit={async (payload) => inspector.capture(payload)} /> : null}
    {inspector.error ? <p className="rounded border border-red-400/25 bg-red-950/15 px-3 py-2 text-[11px] text-red-200" role="alert">{inspector.error}</p> : null}
    <div className="rounded-lg border border-white/10 bg-black/20 p-3 space-y-2"><div className="flex items-center justify-between gap-2"><span className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Retrieval</span><span className="font-mono text-[10px] text-zinc-300">{inspector.retrieval?.mode ?? 'loading'}</span></div><p className="text-[11px] text-zinc-500">{inspector.retrieval ? `${inspector.retrieval.indexed_items} indexed · ${inspector.retrieval.pending_items} pending` : 'Loading local retrieval status…'}</p>{inspector.retrieval && ['unprepared', 'degraded'].includes(inspector.retrieval.state) ? <button type="button" disabled={demoModeActive || inspector.isPreparing} onClick={() => void inspector.prepare()} className="rounded border border-[#7EB3FF]/45 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white disabled:opacity-45">{inspector.isPreparing ? 'Preparing…' : 'Prepare semantic retrieval'}</button> : null}</div>
    <form onSubmit={(event) => { event.preventDefault(); void inspector.refresh() }} className="space-y-2"><input aria-label="Search personal context" value={inspector.filters.query} onChange={(event) => inspector.setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="Search context" className="w-full rounded border border-white/10 bg-zinc-950 px-2.5 py-2 text-xs text-zinc-200" /><select aria-label="Context kind" value={inspector.filters.kind} onChange={(event) => inspector.setFilters((current) => ({ ...current, kind: event.target.value as ContextKind | '' }))} className="w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-200"><option value="">All kinds</option>{KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select><div className="flex flex-wrap gap-2">{STATUSES.map((status) => <label key={status} className="flex items-center gap-1 text-[10px] text-zinc-400"><input type="checkbox" checked={inspector.filters.statuses.includes(status)} onChange={() => changeStatuses(status)} className="accent-[#0F4DB8]" />{status}</label>)}</div><button type="submit" className="font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white">Search</button></form>
    {inspector.isLoading ? <p className="flex items-center gap-2 text-xs text-zinc-500"><Loader2 className="size-3.5 animate-spin" />Loading context…</p> : null}
    {inspector.records.length >= 100 ? <p className="text-[11px] text-amber-200">Showing the newest 100 records. Refine the filters to narrow the list.</p> : null}
    <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">{inspector.records.map((record) => <RecordRow key={record.id} record={record} selected={record.id === inspector.selectedRecordId} onSelect={() => void inspector.selectRecord(record.id)} />)}{!inspector.isLoading && inspector.records.length === 0 ? <p className="text-[11px] text-zinc-500">No matching context records.</p> : null}</div>
    {inspector.isDetailLoading ? <p className="text-xs text-zinc-500">Loading record…</p> : null}
    {detail ? <div className="space-y-3 rounded-lg border border-[#7EB3FF]/25 bg-black/20 p-3"><div><p className={`font-mono text-[10px] uppercase tracking-wide ${statusClass(detail.status)}`}>{detail.kind} · {detail.status}</p><p className="mt-1 text-xs leading-relaxed text-zinc-200">{detail.text}</p></div>{detail.subject ? <div className="text-[11px] text-zinc-400"><p>{detail.subject.name} {detail.predicate ?? ''} {detail.object_entity?.name ?? detail.object_value ?? ''}</p>{detail.subject.aliases.length > 1 ? <p className="mt-1 text-zinc-600">Aliases: {detail.subject.aliases.join(', ')}</p> : null}</div> : null}<div><p className="font-mono text-[9px] uppercase tracking-wide text-zinc-500">Sources</p>{detail.sources.map((source) => <div key={source.id} className="mt-1 rounded border border-white/5 p-2 text-[11px] text-zinc-400"><p className="font-mono text-[9px] text-zinc-500">{source.kind} · {source.locator}</p><p className="mt-1 whitespace-pre-wrap">{source.original_text}</p></div>)}</div>{detail.superseded_by.length > 0 ? <div className="flex flex-wrap gap-1 text-[11px] text-zinc-500"><span>Superseded by:</span>{detail.superseded_by.map((recordId) => <button key={recordId} type="button" onClick={() => void inspector.selectRecord(recordId)} className="text-[#9AC2FF] hover:text-white">Open record</button>)}</div> : null}{detail.related_records.length > 0 ? <div className="space-y-1"><p className="font-mono text-[9px] uppercase tracking-wide text-zinc-500">Related records</p>{detail.related_records.map((record) => <button key={record.id} type="button" onClick={() => void inspector.selectRecord(record.id)} className="block text-left text-[11px] text-[#9AC2FF] hover:text-white">{record.kind}: {record.text}</button>)}</div> : null}<div className="flex flex-wrap gap-2">{detail.status === 'retracted' ? <button type="button" disabled={demoModeActive} onClick={() => void proposeAndRefresh({ operation: 'restore', record_id: detail.id })} className="text-[10px] text-[#9AC2FF] hover:text-white">Restore</button> : <>{['active', 'conflicting'].includes(detail.status) ? <button type="button" disabled={demoModeActive} onClick={() => void proposeAndRefresh({ operation: 'retract', record_id: detail.id })} className="text-[10px] text-red-200 hover:text-white">Retract</button> : null}{detail.status === 'conflicting' ? <button type="button" disabled={demoModeActive} onClick={() => void proposeAndRefresh({ operation: 'set_current', record_id: detail.id })} className="text-[10px] text-[#9AC2FF] hover:text-white">Set current</button> : null}{detail.status === 'active' ? <button type="button" disabled={demoModeActive} onClick={() => setShowCorrection((value) => !value)} className="text-[10px] text-[#9AC2FF] hover:text-white">Correct</button> : null}</>}</div>{showCorrection && detail.status === 'active' ? <CaptureForm label="Correction" disabled={demoModeActive} onSubmit={(capture) => inspector.reconcile({ operation: 'correct', record_id: detail.id, capture })} /> : null}{subject ? <div className="space-y-2 border-t border-white/10 pt-3"><p className="font-mono text-[9px] uppercase tracking-wide text-zinc-500">Entity: {subject.name}</p><div className="flex gap-2"><input aria-label="Add entity alias" value={alias} onChange={(event) => setAlias(event.target.value)} placeholder="Add alias" className="min-w-0 flex-1 rounded border border-white/10 bg-zinc-950 px-2 py-1 text-xs text-zinc-200" /><button type="button" disabled={!alias.trim() || demoModeActive} onClick={() => { void proposeAndRefresh({ operation: 'add_alias', entity_id: subject.id, alias }); setAlias('') }} className="text-[10px] text-[#9AC2FF] disabled:opacity-45">Add</button></div><select aria-label="Merge entity into" value={mergeTargetId} onChange={(event) => setMergeTargetId(event.target.value)} className="w-full rounded border border-white/10 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"><option value="">Merge into…</option>{inspector.entities.filter((entity) => entity.id !== subject.id).map((entity) => <option key={entity.id} value={entity.id}>{entity.name}</option>)}</select>{mergeTargetId ? <button type="button" disabled={demoModeActive} onClick={() => void proposeAndRefresh({ operation: 'merge_entities', source_entity_id: subject.id, target_entity_id: mergeTargetId })} className="text-[10px] text-amber-200 hover:text-white">Propose entity merge</button> : null}</div> : null}</div> : null}
    {inspector.lastCreatedRecordId ? <button type="button" disabled={demoModeActive} onClick={() => void proposeAndRefresh({ operation: 'retract', record_id: inspector.lastCreatedRecordId ?? '' })} className="text-[10px] text-amber-200 hover:text-white">Undo recent saved context</button> : null}
  </section>
}
