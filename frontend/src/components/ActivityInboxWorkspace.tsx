import { ExternalLink, FileText, Inbox, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { UseActivityInboxResult } from '../hooks/useActivityInbox'
import type { ContextKind, ContextReview } from '../types/context'
import type { ActivityContextProposalInput, ActivityDisposition, ActivityReport } from '../types/activity'

const CONTEXT_KINDS: readonly ContextKind[] = [
  'note', 'fact', 'decision', 'preference', 'goal', 'constraint', 'idea', 'observation',
]

function safeExternalUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null
  } catch {
    return null
  }
}

function formatTime(value: string | null): string {
  if (!value) return 'Not supplied'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString()
}

function findingOptions(report: ActivityReport): Array<{ reference: string; label: string; text: string }> {
  if (report.report.findings.length) {
    return report.report.findings.map((finding, index) => ({
      reference: `/findings/${index}`,
      label: finding.title?.trim() || `Finding ${index + 1}`,
      text: finding.text,
    }))
  }
  const options = [{ reference: '/outcome', label: 'Outcome', text: report.report.outcome }]
  if (report.report.markdown_body) options.push({ reference: '/markdown_body', label: 'Imported notes', text: report.report.markdown_body })
  return options
}

function ExternalReference({ value }: { value: string }): ReactElement {
  const url = safeExternalUrl(value)
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all text-[#9AC2FF] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]">
      {value}<ExternalLink className="size-3 shrink-0" aria-hidden />
    </a>
  ) : <span className="break-all text-zinc-300">{value}</span>
}

function DispositionControls({
  value,
  disabled,
  onChange,
}: {
  value: ActivityDisposition
  disabled: boolean
  onChange: (disposition: ActivityDisposition) => void
}): ReactElement {
  return (
    <div className="flex flex-wrap gap-2" aria-label="Inbox disposition">
      {(['new', 'reviewed', 'dismissed'] as const).map((disposition) => (
        <button
          key={disposition}
          type="button"
          disabled={disabled || value === disposition}
          onClick={() => onChange(disposition)}
          className={`rounded-md border px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-50 ${value === disposition ? 'border-[#7EB3FF]/50 bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'border-white/10 text-zinc-400 hover:border-white/25 hover:text-zinc-100'}`}
        >
          {disposition === 'new' && value !== 'new' ? 'Reopen' : disposition}
        </button>
      ))}
    </div>
  )
}

function ContextProposalForm({
  report,
  disabled,
  pending,
  onPropose,
}: {
  report: ActivityReport
  disabled: boolean
  pending: boolean
  onPropose: (input: ActivityContextProposalInput) => Promise<void>
}): ReactElement {
  const options = useMemo(() => findingOptions(report), [report])
  const [reference, setReference] = useState(options[0]?.reference ?? '/outcome')
  const [kind, setKind] = useState<ContextKind>('note')
  const [text, setText] = useState(options[0]?.text ?? '')
  const [subject, setSubject] = useState('')
  const [predicate, setPredicate] = useState('')
  const [objectValue, setObjectValue] = useState('')
  const [effectiveAt, setEffectiveAt] = useState('')

  useEffect(() => {
    const selected = options.find((option) => option.reference === reference) ?? options[0]
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A selected report initializes its proposal fields.
    setReference(selected?.reference ?? '/outcome')
    setText(selected?.text ?? '')
    setSubject('')
    setPredicate('')
    setObjectValue('')
    setEffectiveAt('')
  // eslint-disable-next-line react-hooks/exhaustive-deps -- Change drafts only when the immutable report changes.
  }, [options, report.id])

  const submit = async (): Promise<void> => {
    const input: ActivityContextProposalInput = {
      finding_reference: reference,
      kind,
      text: text.trim(),
    }
    if (subject.trim()) input.subject = subject.trim()
    if (predicate.trim()) input.predicate = predicate.trim()
    if (objectValue.trim()) input.object_value = objectValue.trim()
    if (effectiveAt.trim()) input.effective_at = effectiveAt.trim()
    await onPropose(input)
  }

  return (
    <section className="space-y-3 rounded-lg border border-[#7E22CE]/35 bg-[#160b24]/35 p-3" aria-label="Propose personal context">
      <div>
        <h3 className="font-orbitron text-[11px] uppercase tracking-[0.16em] text-[#D8B4FE]">Propose personal context</h3>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">This preserves the selected original evidence and creates a pending Cortex review. It does not alter the report.</p>
      </div>
      <label className="block text-xs text-zinc-300">
        Finding
        <select value={reference} disabled={disabled || pending} onChange={(event) => {
          const next = options.find((option) => option.reference === event.target.value)
          setReference(event.target.value)
          if (next) setText(next.text)
        }} className="mt-1 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45">
          {options.map((option) => <option key={option.reference} value={option.reference}>{option.label}</option>)}
        </select>
      </label>
      <label className="block text-xs text-zinc-300">
        Context kind
        <select value={kind} disabled={disabled || pending} onChange={(event) => setKind(event.target.value as ContextKind)} className="mt-1 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45">
          {CONTEXT_KINDS.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label className="block text-xs text-zinc-300">
        Proposed context
        <textarea value={text} disabled={disabled || pending} onChange={(event) => setText(event.target.value)} rows={4} className="mt-1 w-full resize-y rounded-md border border-white/10 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45" />
      </label>
      <details className="rounded-md border border-white/10 px-2.5 py-2">
        <summary className="cursor-pointer text-xs text-zinc-300">Structured context fields</summary>
        <p className="mt-2 text-xs text-zinc-500">Supply subject, predicate, and one object value together, or leave all three blank.</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <label className="text-xs text-zinc-400">Subject<input value={subject} disabled={disabled || pending} onChange={(event) => setSubject(event.target.value)} className="mt-1 w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45" /></label>
          <label className="text-xs text-zinc-400">Predicate<input value={predicate} disabled={disabled || pending} onChange={(event) => setPredicate(event.target.value)} className="mt-1 w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45" /></label>
          <label className="text-xs text-zinc-400">Object value<input value={objectValue} disabled={disabled || pending} onChange={(event) => setObjectValue(event.target.value)} className="mt-1 w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45" /></label>
        </div>
        <label className="mt-2 block text-xs text-zinc-400">Effective time (ISO 8601)<input value={effectiveAt} disabled={disabled || pending} onChange={(event) => setEffectiveAt(event.target.value)} className="mt-1 w-full rounded border border-white/10 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-[#D8B4FE] focus:outline-none disabled:opacity-45" /></label>
      </details>
      <button type="button" disabled={disabled || pending || !text.trim()} onClick={() => void submit()} className="inline-flex min-h-9 items-center rounded-md border border-[#A855F7]/50 bg-[#7E22CE]/20 px-3 text-xs text-[#F0D8FF] hover:bg-[#7E22CE]/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D8B4FE] disabled:cursor-not-allowed disabled:opacity-45">
        {pending ? 'Creating review…' : 'Create pending review'}
      </button>
    </section>
  )
}

export function ActivityInboxWorkspace({
  inbox,
  demoModeActive,
  sandboxMode,
  onOpenReview,
}: {
  inbox: UseActivityInboxResult
  demoModeActive: boolean
  sandboxMode: boolean
  onOpenReview: (review: ContextReview) => Promise<string | null>
}): ReactElement {
  const [navigationError, setNavigationError] = useState<string | null>(null)
  const detail = inbox.detail
  const disabled = demoModeActive || Boolean(inbox.mutation)

  const openReview = async (review: ContextReview): Promise<void> => {
    const error = await onOpenReview(review)
    setNavigationError(error)
  }

  return (
    <section className="mx-auto flex min-h-0 w-full max-w-[1520px] flex-1 flex-col gap-4 px-4 pb-6 pt-2 sm:px-6" aria-label="External activity inbox">
      <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-white/10 bg-black/30 px-4 py-3">
        <div className="flex items-start gap-3"><span className="inline-flex size-9 items-center justify-center rounded-lg border border-[#0F4DB8]/40 bg-[#082F7A]/20 text-[#A5C7FF]"><Inbox className="size-4" aria-hidden /></span><div><h1 className="font-orbitron text-sm uppercase tracking-[0.18em] text-zinc-100">Inbox</h1><p className="mt-1 max-w-2xl text-xs leading-relaxed text-zinc-400">Untrusted reports from configured external sources. Reading and organizing them never changes personal context.</p></div></div>
        <button type="button" onClick={() => void inbox.refresh()} disabled={demoModeActive || inbox.isLoading || inbox.isDetailLoading} className="inline-flex min-h-9 items-center gap-2 rounded-md border border-white/10 px-3 text-xs text-zinc-300 hover:border-white/25 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"><RefreshCw className={`size-3.5 ${inbox.isLoading || inbox.isDetailLoading ? 'animate-spin' : ''}`} aria-hidden />Refresh</button>
      </header>
      {demoModeActive ? <p className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-300">External activity is unavailable in demo mode.</p> : null}
      {sandboxMode ? <p className="rounded-lg border border-amber-400/25 bg-amber-950/25 px-3 py-2 text-sm text-amber-100">Sandbox reports and reviews are isolated from production.</p> : null}
      {inbox.error ? <p role="alert" className="rounded-lg border border-red-400/30 bg-red-950/30 px-3 py-2 text-sm text-red-100">{inbox.error}</p> : null}
      {navigationError ? <p role="alert" className="rounded-lg border border-amber-400/30 bg-amber-950/30 px-3 py-2 text-sm text-amber-100">{navigationError}</p> : null}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(15rem,0.72fr)_minmax(0,1.5fr)]">
        <aside className="min-h-0 rounded-xl border border-white/10 bg-black/25 p-3 lg:overflow-y-auto" aria-label="Activity reports">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
            <label className="text-xs text-zinc-400">Source<select value={inbox.sourceFilter} onChange={(event) => inbox.setSourceFilter(event.target.value)} className="mt-1 w-full rounded-md border border-white/10 bg-zinc-950 px-2 py-2 text-sm text-zinc-100 focus:border-[#7EB3FF] focus:outline-none"><option value="all">All sources</option>{inbox.sources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}</select></label>
            <label className="text-xs text-zinc-400">Disposition<select value={inbox.dispositionFilter} onChange={(event) => inbox.setDispositionFilter(event.target.value as 'all' | ActivityDisposition)} className="mt-1 w-full rounded-md border border-white/10 bg-zinc-950 px-2 py-2 text-sm text-zinc-100 focus:border-[#7EB3FF] focus:outline-none"><option value="all">All dispositions</option><option value="new">New</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option></select></label>
          </div>
          {inbox.isLoading ? <p className="mt-4 flex items-center gap-2 text-sm text-zinc-400"><Loader2 className="size-4 animate-spin" aria-hidden />Loading reports…</p> : null}
          {!inbox.isLoading && !inbox.reports.length ? <p className="mt-4 rounded-md border border-dashed border-white/10 p-3 text-sm leading-relaxed text-zinc-500">No reports match these filters.</p> : null}
          {inbox.reports.length >= 100 ? <p className="mt-3 text-xs text-amber-100">Showing the newest 100 reports. Refine the filters to narrow the list.</p> : null}
          <div className="mt-3 space-y-2">{inbox.reports.map((report) => <button key={report.id} type="button" onClick={() => inbox.selectReport(report.id)} aria-pressed={inbox.selectedReportId === report.id} className={`block w-full rounded-lg border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${inbox.selectedReportId === report.id ? 'border-[#0F4DB8]/70 bg-[#082F7A]/20' : 'border-white/10 bg-white/[0.02] hover:border-white/25'}`}><span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium text-zinc-100">{report.report.title}</span><span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-zinc-500">{report.disposition}</span></span><span className="mt-1 block truncate text-xs text-zinc-400">{report.client_display_name} · {report.report.task_status}</span><span className="mt-1 block font-mono text-[10px] text-zinc-600">{formatTime(report.received_at)}</span></button>)}</div>
        </aside>
        <article className="min-w-0 rounded-xl border border-white/10 bg-black/25 p-4 lg:overflow-y-auto" aria-live="polite">
          {inbox.isDetailLoading ? <p className="flex items-center gap-2 text-sm text-zinc-400"><Loader2 className="size-4 animate-spin" aria-hidden />Loading report…</p> : null}
          {!inbox.isDetailLoading && !detail ? <div className="flex min-h-48 flex-col items-center justify-center gap-2 text-center text-zinc-500"><FileText className="size-7" aria-hidden /><p>Select a report to inspect its immutable contents.</p></div> : null}
          {detail ? <div className="space-y-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#A5C7FF]">{detail.client_display_name} · {detail.report.task_status}</p><h2 className="mt-1 break-words font-orbitron text-lg tracking-wide text-zinc-100">{detail.report.title}</h2><p className="mt-2 text-xs text-zinc-500">Received {formatTime(detail.received_at)} · Occurred {formatTime(detail.report.occurred_at)}</p></div><DispositionControls value={detail.disposition} disabled={disabled} onChange={(disposition) => void inbox.setDisposition(disposition)} /></div>
            <p className="rounded-md border border-white/10 bg-zinc-950/40 p-3 text-sm leading-relaxed whitespace-pre-wrap text-zinc-200">{detail.report.outcome}</p>
            {detail.report.native_task_url ? <div><p className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Native task</p><ExternalReference value={detail.report.native_task_url} /></div> : null}
            <div className="grid gap-4 md:grid-cols-2"><div><p className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Evidence</p>{detail.report.evidence_links.length ? <ul className="mt-1 space-y-1 text-sm">{detail.report.evidence_links.map((value) => <li key={value}><ExternalReference value={value} /></li>)}</ul> : <p className="mt-1 text-sm text-zinc-500">No evidence links supplied.</p>}</div><div><p className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Artifacts</p>{detail.report.artifact_references.length ? <ul className="mt-1 space-y-1 text-sm">{detail.report.artifact_references.map((value) => <li key={value}><ExternalReference value={value} /></li>)}</ul> : <p className="mt-1 text-sm text-zinc-500">No artifact references supplied.</p>}</div></div>
            {(detail.report.subjects.length || detail.report.projects.length) ? <p className="text-xs leading-relaxed text-zinc-500">Untrusted reported labels: {[...detail.report.subjects, ...detail.report.projects].join(' · ')}</p> : null}
            {detail.report.unresolved_questions.length ? <section><h3 className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Unresolved questions</h3><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-zinc-300">{detail.report.unresolved_questions.map((question) => <li key={question}>{question}</li>)}</ul></section> : null}
            {detail.report.suggested_follow_up ? <p className="text-sm text-zinc-300"><span className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Suggested follow-up</span><br />{detail.report.suggested_follow_up}</p> : null}
            {detail.report.markdown_body ? <section className="rounded-lg border border-white/10 bg-zinc-950/30 p-3"><h3 className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">Imported notes</h3><div className="prose prose-invert prose-sm mt-2 max-w-none break-words text-zinc-300"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{ a: ({ href, children }) => { const url = safeExternalUrl(href ?? null); return url ? <a href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span> }, img: ({ alt }) => <span>{alt ? `Image omitted: ${alt}` : 'Image omitted.'}</span> }}>{detail.report.markdown_body}</ReactMarkdown></div></section> : null}
            <ContextProposalForm report={detail} disabled={demoModeActive} pending={inbox.mutation === 'proposal'} onPropose={async (input) => { const review = await inbox.proposeContext(input); if (review) await openReview(review) }} />
            <section className="rounded-lg border border-white/10 bg-white/[0.02] p-3"><h3 className="font-orbitron text-[11px] uppercase tracking-[0.16em] text-zinc-300">Linked reviews</h3>{!inbox.linkedReviews.length ? <p className="mt-2 text-sm text-zinc-500">No context reviews have been created from this report.</p> : <ul className="mt-2 space-y-2">{inbox.linkedReviews.map((link) => <li key={link.review.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/10 px-2.5 py-2"><span className="text-sm text-zinc-300">{link.finding_reference} · {link.review.operation} · <span className="text-zinc-500">{link.review.decision}</span></span><button type="button" disabled={demoModeActive} onClick={() => void openReview(link.review)} className="text-xs text-[#A5C7FF] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:opacity-45">Open in Cortex Review</button></li>)}</ul>}</section>
          </div> : null}
        </article>
      </div>
    </section>
  )
}
