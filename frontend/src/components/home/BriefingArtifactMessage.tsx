import type { ReactElement } from 'react'

import { useBriefingPresentation } from '../../hooks/useBriefingPresentation'
import { formatBriefingTime } from '../../lib/briefingFormat'
import type { BriefingSessionDetail } from '../../types/briefings'
import {
  BriefingCoverage,
  BriefingEvidenceRecords,
  BriefingItemTrustLabels,
  type BriefingEvidenceState,
} from './BriefingEvidence'

type Props = {
  session: BriefingSessionDetail
  isLoadingSession: boolean
  evidence: Omit<BriefingEvidenceState, 'sessionId'>
  onMarkPresented: (sessionId: string) => Promise<void>
}

/** Structured opening message of a completed briefing session's conversation. */
export function BriefingArtifactMessage({ session, isLoadingSession, evidence, onMarkPresented }: Props): ReactElement | null {
  const presentationRef = useBriefingPresentation({ session, isLoadingSession, onMarkPresented })
  const artifact = session.artifact
  if (!artifact) return null
  const evidenceState: BriefingEvidenceState = { ...evidence, sessionId: session.id }
  const referencedEvidenceIds = new Set(artifact.sections.flatMap((section) => section.items.flatMap((item) => item.evidence_ids)))
  const otherEvidenceIds = session.evidence_ids.filter((id) => !referencedEvidenceIds.has(id))
  const isDemo = session.configuration.execution_kind === 'demo'
  return <article data-testid="briefing-artifact" className="space-y-4" aria-label={`${session.configuration.profile.label} briefing`}>
    <header ref={presentationRef}>
      <p className="font-orbitron text-[11px] uppercase tracking-[0.15em] text-[#A5C7FF]">{session.configuration.profile.label} briefing</p>
      <p className="mt-1 font-mono text-[10px] text-zinc-500">
        {formatBriefingTime(artifact.created_at)} · {isDemo ? 'Deterministic demo fixture' : session.configuration.model.model_id}
      </p>
      {isDemo ? <p className="mt-2 rounded-md border border-blue-400/15 bg-blue-950/20 px-2 py-1.5 text-[10px] text-blue-100">DEMO fixture. No model was run and no live personal sources were read.</p> : null}
      {artifact.sections.length === 0 ? <p className="mt-2 text-sm text-zinc-300">No briefing items were produced.</p> : null}
    </header>
    {artifact.sections.map((section) => <section key={section.id} className="space-y-2">
      <h3 className="font-orbitron text-[10px] uppercase tracking-wider text-[#A5C7FF]">{section.title}</h3>
      {section.items.map((item) => <article key={item.id} className="rounded-lg border border-white/10 bg-white/[0.025] p-2.5">
        <p className="mb-1 font-mono text-[9px] capitalize text-zinc-400">{item.category.replaceAll('_', ' ')}</p>
        <h4 className="text-xs font-medium text-zinc-100">{item.title}</h4>
        <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">{item.body}</p>
        <BriefingItemTrustLabels item={item} />
        <details className="mt-2 border-t border-white/5 pt-2">
          <summary className="cursor-pointer font-mono text-[9px] uppercase tracking-wider text-zinc-400">Evidence ({item.evidence_ids.length})</summary>
          <BriefingEvidenceRecords evidenceIds={item.evidence_ids} state={evidenceState} />
        </details>
      </article>)}
    </section>)}
    {otherEvidenceIds.length > 0 ? <details className="border-t border-white/10 pt-3">
      <summary className="cursor-pointer font-mono text-[9px] uppercase tracking-wider text-zinc-500">Other captured evidence ({otherEvidenceIds.length})</summary>
      <BriefingEvidenceRecords evidenceIds={otherEvidenceIds} state={evidenceState} />
    </details> : null}
    <BriefingCoverage artifact={artifact} />
  </article>
}
