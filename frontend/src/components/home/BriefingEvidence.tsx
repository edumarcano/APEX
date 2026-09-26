import type { ReactElement, SyntheticEvent } from 'react'

import { formatBriefingTime } from '../../lib/briefingFormat'
import type { BriefingArtifact, BriefingArtifactItem, BriefingEvidence } from '../../types/briefings'

export type BriefingEvidenceState = {
  sessionId: string
  evidenceById: Record<string, BriefingEvidence>
  loadingIds: string[]
  errors: Record<string, string>
  onLoadEvidence: (sessionId: string, evidenceId: string) => Promise<void>
}

export function BriefingEvidenceRecords({
  evidenceIds,
  state,
  isCitedInArtifact = true,
}: {
  evidenceIds: string[]
  state: BriefingEvidenceState
  isCitedInArtifact?: boolean
}): ReactElement {
  const { sessionId, evidenceById, loadingIds, errors, onLoadEvidence } = state
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
          {source ? <span className="ml-2 text-zinc-500">{source.included_in_synthesis ? 'sent to synthesis' : 'not sent to synthesis'} · {isCitedInArtifact ? 'cited in briefing' : 'not cited in briefing'}</span> : null}
        </summary>
        {loadingIds.includes(id) ? <p className="mt-2 text-xs text-zinc-500" role="status">Loading saved evidence…</p> : null}
        {errors[id] ? <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-red-200" role="alert"><span>{errors[id]}</span><button type="button" onClick={() => void onLoadEvidence(sessionId, id)} className="text-[#A5C7FF] hover:text-white">Retry</button></div> : null}
        {source ? <>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[10px] text-zinc-400">
            <dt>Source ID</dt><dd className="break-all text-zinc-300">{source.source_id}</dd>
            <dt>Identity</dt><dd>{source.identity_kind}</dd>
            <dt>Revision</dt><dd className="break-all">{source.revision ?? 'Unavailable'}{source.revision_kind !== 'none' ? ' (' + source.revision_kind + ')' : ''}</dd>
            {source.comparison_role ? <><dt>Snapshot role</dt><dd>{source.comparison_role}{source.change_kind ? ` · ${source.change_kind.replaceAll('_', ' ')}` : ''}</dd></> : null}
            {source.comparison_pair_id ? <><dt>Comparison pair</dt><dd className="break-all">{source.comparison_pair_id}</dd></> : null}
            <dt>Observed</dt><dd>{source.observed_at ? formatBriefingTime(source.observed_at) : 'Unknown'}</dd>
            <dt>Effective</dt><dd>{source.effective_at ? formatBriefingTime(source.effective_at) : 'Unknown'}</dd>
            <dt>Trust</dt><dd className={source.trust === 'untrusted' ? 'text-amber-200' : ''}>{source.trust}</dd>
          </dl>
          {source.trust === 'untrusted' ? <p className="mt-2 rounded bg-amber-950/30 px-2 py-1 text-[10px] text-amber-100">External report content is attributed and untrusted. Treat its claims as reports, not verified facts.</p> : null}
          {source.content ? <p className="mt-2 whitespace-pre-wrap break-words border-l border-white/10 pl-2 text-xs leading-relaxed text-zinc-300">{source.content}</p> : <p className="mt-2 text-xs text-zinc-500">{source.unavailable_reason ?? 'Source content is unavailable.'}</p>}
        </> : null}
      </details>
    })}
  </div>
}

/** Trust labels derived from the artifact itself, visible before evidence is fetched. */
export function BriefingItemTrustLabels({ item }: { item: BriefingArtifactItem }): ReactElement | null {
  const external = item.category === 'external_report' || item.record_references.some((reference) => reference.kind === 'external_activity')
  const pending = item.category === 'pending_review' || item.record_references.some((reference) => reference.kind === 'context_review')
  if (!external && !pending) return null
  return <>
    {external ? <p className="mt-2 text-[10px] font-medium text-amber-200">Includes an attributed, untrusted external report.</p> : null}
    {pending ? <p className="mt-2 text-[10px] font-medium text-amber-200">Includes a pending review that has not been accepted into personal context.</p> : null}
  </>
}

export function BriefingCoverage({
  artifact,
  showComparisonSummary = true,
}: { artifact: BriefingArtifact; showComparisonSummary?: boolean }): ReactElement | null {
  if (artifact.coverage.length === 0 && artifact.limitations.length === 0 && !artifact.comparison) return null
  return <details className="border-t border-white/10 pt-3">
    <summary className="cursor-pointer font-mono text-[9px] uppercase tracking-wider text-zinc-400">Source coverage and limits ({artifact.coverage.length})</summary>
    <div className="mt-2 space-y-2">
      {artifact.comparison ? <section aria-label="Source comparison" className="rounded border border-blue-400/15 bg-blue-950/15 px-2 py-2 text-[10px]">
        {showComparisonSummary ? <p className="font-medium text-blue-100">{artifact.comparison.summary}</p> : null}
        <ul className="mt-1 space-y-1 text-zinc-400">
          {artifact.comparison.sources.map((source) => <li key={source.source}>
            <span className="capitalize text-zinc-200">{source.source.replaceAll('_', ' ')}</span> · {source.status}
            {source.baseline_snapshot_at ? ` · baseline ${formatBriefingTime(source.baseline_snapshot_at)}` : ''}
            {source.current_snapshot_at ? ` · current ${formatBriefingTime(source.current_snapshot_at)}` : ''}
            {source.reason ? ` · ${source.reason.replaceAll('_', ' ')}` : ''}
          </li>)}
        </ul>
      </section> : null}
      {artifact.coverage.map((coverage) => <div key={coverage.source + coverage.scope} className="rounded border border-white/5 px-2 py-1.5 text-[10px]">
        <p className="font-medium capitalize text-zinc-200">{coverage.source.replaceAll('_', ' ')} · {coverage.scope}</p>
        <p className="mt-0.5 capitalize text-zinc-400">{coverage.status}{coverage.truncated ? ' · truncated' : ''}{coverage.observed_at ? ' · observed ' + formatBriefingTime(coverage.observed_at) : ''}</p>
        {coverage.reason ? <p className="mt-1 text-amber-200">{coverage.reason}</p> : null}
      </div>)}
    </div>
    {artifact.limitations.length ? <ul className="mt-2 list-disc space-y-1 pl-4 text-[10px] text-amber-100">{artifact.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul> : null}
  </details>
}
