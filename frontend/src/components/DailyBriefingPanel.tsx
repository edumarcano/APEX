import { useCallback, useEffect, useRef } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'

import type {
  BriefingEvidence,
  BriefingSessionDetail,
  BriefingSessionSummary,
} from '../types/briefings'
import { ApexAssistantThread } from './ApexAssistantRuntime'

type Props = {
  sessions: BriefingSessionSummary[]
  selectedSessionId: string | null
  session: BriefingSessionDetail | null
  evidenceById: Record<string, BriefingEvidence>
  evidenceLoadingIds: string[]
  evidenceErrors: Record<string, string>
  isLoadingSessions: boolean
  isLoadingSession: boolean
  isGenerating: boolean
  hasActiveSession: boolean
  conversationReady: boolean
  canGenerateDaily: boolean
  canFollowUp: boolean
  error: string | null
  onGenerateDaily: () => void
  onOpenSession: (sessionId: string) => void
  onOpenConversation: (conversationId: string) => void
  onLoadEvidence: (sessionId: string, evidenceId: string) => Promise<void>
  onCancel: (sessionId: string) => void
  onMarkPresented: (sessionId: string) => Promise<void>
  onClose: () => void
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function EvidenceRecords({
  sessionId,
  evidenceIds,
  evidenceById,
  loadingIds,
  errors,
  onLoadEvidence,
}: {
  sessionId: string
  evidenceIds: string[]
  evidenceById: Record<string, BriefingEvidence>
  loadingIds: string[]
  errors: Record<string, string>
  onLoadEvidence: (sessionId: string, evidenceId: string) => Promise<void>
}): ReactElement {
  if (evidenceIds.length === 0) return <p className="mt-2 text-xs text-zinc-500">No source records were captured for this item.</p>
  return <div className="mt-2 space-y-2">
    {evidenceIds.map((id) => {
      const source = evidenceById[id]
      return <details key={id} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2" onToggle={(event: SyntheticEvent<HTMLDetailsElement>) => {
        if (event.currentTarget.open && !source && !loadingIds.includes(id)) void onLoadEvidence(sessionId, id)
      }}>
        <summary className="cursor-pointer text-xs text-zinc-200">
          {source ? <span className={source.trust === 'untrusted' ? 'text-amber-200' : 'text-[#A5C7FF]'}>
            {source.trust === 'untrusted' ? 'Untrusted external report' : source.trust === 'pending' ? 'Pending context' : source.source.replaceAll('_', ' ')}
          </span> : <span>Inspect source record {id.slice(0, 8)}</span>}
          {source ? <span className="ml-2 text-zinc-500">{source.included_in_synthesis ? 'used in synthesis' : 'not used in synthesis'}</span> : null}
        </summary>
        {loadingIds.includes(id) ? <p className="mt-2 text-xs text-zinc-500" role="status">Loading saved evidence…</p> : null}
        {errors[id] ? <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-red-200" role="alert"><span>{errors[id]}</span><button type="button" onClick={() => void onLoadEvidence(sessionId, id)} className="text-[#A5C7FF] hover:text-white">Retry</button></div> : null}
        {source ? <>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[10px] text-zinc-400">
            <dt>Source ID</dt><dd className="break-all text-zinc-300">{source.source_id}</dd>
            <dt>Identity</dt><dd>{source.identity_kind}</dd>
            <dt>Revision</dt><dd className="break-all">{source.revision ?? 'Unavailable'}{source.revision_kind !== 'none' ? ' (' + source.revision_kind + ')' : ''}</dd>
            <dt>Observed</dt><dd>{source.observed_at ? formatTime(source.observed_at) : 'Unknown'}</dd>
            <dt>Effective</dt><dd>{source.effective_at ? formatTime(source.effective_at) : 'Unknown'}</dd>
            <dt>Trust</dt><dd className={source.trust === 'untrusted' ? 'text-amber-200' : ''}>{source.trust}</dd>
          </dl>
          {source.trust === 'untrusted' ? <p className="mt-2 rounded bg-amber-950/30 px-2 py-1 text-[10px] text-amber-100">External report content is attributed and untrusted. Treat its claims as reports, not verified facts.</p> : null}
          {source.content ? <p className="mt-2 whitespace-pre-wrap break-words border-l border-white/10 pl-2 text-xs leading-relaxed text-zinc-300">{source.content}</p> : <p className="mt-2 text-xs text-zinc-500">{source.unavailable_reason ?? 'Source content is unavailable.'}</p>}
        </> : null}
      </details>
    })}
  </div>
}

export function DailyBriefingPanel({
  sessions,
  selectedSessionId,
  session,
  evidenceById,
  evidenceLoadingIds,
  evidenceErrors,
  isLoadingSessions,
  isLoadingSession,
  isGenerating,
  hasActiveSession,
  conversationReady,
  canGenerateDaily,
  canFollowUp,
  error,
  onGenerateDaily,
  onOpenSession,
  onOpenConversation,
  onLoadEvidence,
  onCancel,
  onMarkPresented,
  onClose,
}: Props): ReactElement {
  const artifactVisibilityRef = useRef<HTMLDivElement | null>(null)
  const visibleRef = useRef(false)
  const acknowledgedRef = useRef(new Set<string>())
  const acknowledgeIfVisible = useCallback((): void => {
    if (!session || !visibleRef.current || document.visibilityState !== 'visible' || session.presented_at || acknowledgedRef.current.has(session.id)) return
    acknowledgedRef.current.add(session.id)
    void onMarkPresented(session.id).catch(() => acknowledgedRef.current.delete(session.id))
  }, [onMarkPresented, session])
  useEffect(() => {
    visibleRef.current = false
    const element = artifactVisibilityRef.current
    if (!element || isLoadingSession || session?.run_status !== 'completed' || !session.artifact || session.presented_at) return undefined
    if (typeof IntersectionObserver === 'undefined') {
      const rect = element.getBoundingClientRect()
      visibleRef.current = rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
      acknowledgeIfVisible()
      return undefined
    }
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      visibleRef.current = Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.5)
      acknowledgeIfVisible()
    }, { threshold: [0.5] })
    const handleVisibility = (): void => acknowledgeIfVisible()
    document.addEventListener('visibilitychange', handleVisibility)
    observer.observe(element)
    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [acknowledgeIfVisible, isLoadingSession, session])
  const artifact = session?.artifact ?? null
  const isRunning = session ? ['queued', 'running', 'cancelling'].includes(session.run_status) : false
  const referencedEvidenceIds = new Set(artifact?.sections.flatMap((section) => section.items.flatMap((item) => item.evidence_ids)) ?? [])
  const otherEvidenceIds = session?.evidence_ids.filter((id) => !referencedEvidenceIds.has(id)) ?? []
  return <section className="mt-3 flex max-h-[58vh] min-h-[24rem] w-full min-w-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-zinc-950/90 shadow-[0_18px_70px_rgba(0,0,0,0.45)]" aria-labelledby="daily-briefing-title">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2.5">
      <div className="min-w-0">
        <h2 id="daily-briefing-title" className="font-orbitron text-[11px] uppercase tracking-[0.15em] text-[#A5C7FF]">Daily briefing</h2>
        <p className="mt-0.5 text-[10px] text-zinc-500">Saved artifact, original evidence, and its APEX conversation</p>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={onGenerateDaily} disabled={!canGenerateDaily || hasActiveSession || isGenerating} className="rounded-md border border-[#1F6FE5]/50 bg-[#0F4DB8]/20 px-2.5 py-1.5 font-mono text-[10px] text-[#DCEAFF] hover:bg-[#0F4DB8]/35 disabled:cursor-not-allowed disabled:opacity-40">{isGenerating ? 'Starting…' : 'New Daily'}</button>
        <button type="button" onClick={onClose} className="rounded-md border border-white/10 px-2 py-1.5 font-mono text-[10px] text-zinc-400 hover:text-white" aria-label="Close Daily briefing panel">Close</button>
      </div>
    </header>
    <nav className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-white/10 px-3 py-2" aria-label="Saved Daily sessions">
      {isLoadingSessions ? <span className="text-[10px] text-zinc-500" role="status">Loading saved sessions…</span> : sessions.length === 0 ? <span className="text-[10px] text-zinc-500">No saved Daily sessions yet.</span> : sessions.map((item) => (
        <button key={item.id} type="button" onClick={() => onOpenSession(item.id)} aria-current={item.id === selectedSessionId ? 'page' : undefined} className={'shrink-0 rounded-md border px-2 py-1 text-left ' + (item.id === selectedSessionId ? 'border-[#1F6FE5]/50 bg-[#0F4DB8]/20 text-white' : 'border-white/10 text-zinc-400 hover:text-white')}>
          <span className="block font-mono text-[9px]">{formatTime(item.created_at)}</span>
          <span className="block text-[9px] capitalize">{item.run_status}</span>
        </button>
      ))}
    </nav>
    {error ? <p className="shrink-0 border-b border-red-500/20 bg-red-950/20 px-3 py-2 text-xs text-red-200" role="alert">{error}</p> : null}
    {!session ? <div className="flex min-h-0 flex-1 items-center justify-center p-5 text-center text-xs text-zinc-500">{isLoadingSession ? 'Loading saved Daily…' : 'Prepare Daily to save your current briefing and conversation.'}</div> : (
      <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-2">
        <div className="min-h-0 overflow-y-auto border-b border-white/10 p-3 xl:border-b-0 xl:border-r">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">{session.configuration.execution_kind === 'demo' ? 'Deterministic demo fixture' : session.configuration.model.model_id}</p>
              <p className="mt-1 text-[10px] text-zinc-500">{formatTime(session.created_at)} · <span className="capitalize">{session.run_status}</span></p>
            </div>
            {isRunning ? <button type="button" disabled={session.run_status === 'cancelling'} onClick={() => onCancel(session.id)} className="rounded border border-red-500/25 px-2 py-1 font-mono text-[9px] text-red-200 hover:bg-red-950/30 disabled:opacity-40">Stop</button> : null}
          </div>
          {session.configuration.execution_kind === 'demo' ? <p className="mb-3 rounded-md border border-blue-400/15 bg-blue-950/20 px-2 py-1.5 text-[10px] text-blue-100">DEMO fixture. No model was run and no live personal sources were read.</p> : null}
          {isRunning ? <p className="mb-3 animate-pulse font-mono text-[10px] uppercase tracking-wider text-[#A5C7FF]" role="status">Preparing and synthesizing Daily from the available snapshot…</p> : null}
          {session.run_status === 'failed' || session.run_status === 'interrupted' || session.run_status === 'cancelled' ? <p className="mb-3 rounded-md border border-amber-400/20 bg-amber-950/15 px-2 py-1.5 text-xs text-amber-100">{session.run_error_code === 'invalid_model_output' ? 'The model response did not pass Daily validation after one repair attempt. Start a new Daily run to try again.' : `This Daily run ${session.run_status}. It did not produce a completed artifact.`}</p> : null}
          {!artifact && !isRunning && !isLoadingSession ? <p className="text-xs text-zinc-500">No completed artifact is available for this session.</p> : null}
          {artifact ? <div data-testid="daily-artifact" className="space-y-4">
            <div ref={artifactVisibilityRef}>
              <p className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">Saved Daily · {formatTime(artifact.created_at)}</p>
              {artifact.sections.length === 0 ? <p className="mt-2 text-sm text-zinc-300">No briefing items were produced.</p> : null}
            </div>
            {artifact.sections.map((section) => <section key={section.id} className="space-y-2">
              <h3 className="font-orbitron text-[10px] uppercase tracking-wider text-[#A5C7FF]">{section.title}</h3>
              {section.items.map((item) => <article key={item.id} className="rounded-lg border border-white/10 bg-white/[0.025] p-2.5">
                <p className="mb-1 font-mono text-[9px] capitalize text-zinc-400">{item.category.replaceAll('_', ' ')}</p>
                <h4 className="text-xs font-medium text-zinc-100">{item.title}</h4>
                <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">{item.body}</p>
                {item.category === 'external_report' || item.record_references.some((reference) => reference.kind === 'external_activity') ? <p className="mt-2 text-[10px] font-medium text-amber-200">Includes an attributed, untrusted external report.</p> : null}
                {item.category === 'pending_review' || item.record_references.some((reference) => reference.kind === 'context_review') ? <p className="mt-2 text-[10px] font-medium text-amber-200">Includes a pending review that has not been accepted into personal context.</p> : null}
                <details className="mt-2 border-t border-white/5 pt-2">
                  <summary className="cursor-pointer font-mono text-[9px] uppercase tracking-wider text-zinc-400">Evidence ({item.evidence_ids.length})</summary>
                  <EvidenceRecords sessionId={session.id} evidenceIds={item.evidence_ids} evidenceById={evidenceById} loadingIds={evidenceLoadingIds} errors={evidenceErrors} onLoadEvidence={onLoadEvidence} />
                </details>
              </article>)}
            </section>)}
            {otherEvidenceIds.length > 0 ? <section className="border-t border-white/10 pt-3">
              <h3 className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">Other captured evidence</h3>
              <EvidenceRecords sessionId={session.id} evidenceIds={otherEvidenceIds} evidenceById={evidenceById} loadingIds={evidenceLoadingIds} errors={evidenceErrors} onLoadEvidence={onLoadEvidence} />
            </section> : null}
            {artifact.coverage.length > 0 ? <details className="border-t border-white/10 pt-3">
              <summary className="cursor-pointer font-mono text-[9px] uppercase tracking-wider text-zinc-400">Source coverage and limits ({artifact.coverage.length})</summary>
              <div className="mt-2 space-y-2">
                {artifact.coverage.map((coverage) => <div key={coverage.source + coverage.scope} className="rounded border border-white/5 px-2 py-1.5 text-[10px]">
                  <p className="font-medium capitalize text-zinc-200">{coverage.source.replaceAll('_', ' ')} · {coverage.scope}</p>
                  <p className="mt-0.5 capitalize text-zinc-400">{coverage.status}{coverage.truncated ? ' · truncated' : ''}{coverage.observed_at ? ' · observed ' + formatTime(coverage.observed_at) : ''}</p>
                  {coverage.reason ? <p className="mt-1 text-amber-200">{coverage.reason}</p> : null}
                </div>)}
              </div>
              {artifact.limitations.length ? <ul className="mt-2 list-disc space-y-1 pl-4 text-[10px] text-amber-100">{artifact.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul> : null}
            </details> : null}
          </div> : null}
        </div>
        <section className="flex min-h-0 flex-col" aria-label="Daily follow-up conversation">
          <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-3 py-2">
            <p className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">Continue this conversation</p>
            {conversationReady ? <span className="text-[9px] text-emerald-200">Saved session linked</span> : session.conversation_id ? <button type="button" onClick={() => onOpenConversation(session.conversation_id)} className="text-[9px] text-[#A5C7FF] hover:text-white">Open conversation</button> : null}
          </div>
          {conversationReady ? <ApexAssistantThread disabled={!canFollowUp || isRunning} /> : <div className="flex min-h-0 flex-1 items-center justify-center p-5 text-center text-xs text-zinc-500">{isLoadingSession ? 'Loading saved conversation…' : 'Open this saved session to continue its conversation.'}</div>}
        </section>
      </div>
    )}
  </section>
}
