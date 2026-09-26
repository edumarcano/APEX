import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useCallback, useState, type ReactElement, type ReactNode } from 'react'

import { useCompactLayout } from '../../hooks/useCompactLayout'
import type { BriefingLayoutPhase, HomeActiveView } from '../../hooks/useHomeView'
import { parseAgentQueryResponse } from '../../lib/cortexResponse'
import type { BriefingSessionDetail } from '../../types/briefings'
import { ApexAssistantThread } from '../ApexAssistantRuntime'
import { BriefingArtifactMessage } from './BriefingArtifactMessage'
import type { BriefingEvidenceState } from './BriefingEvidence'
import { BriefingProfilePanel, type BriefingProfilePanelProps } from './BriefingProfilePanel'
import { CompactToolResults } from './CompactToolResults'
import { HomeIdentityMark, HomeViewSwitcher, type HomeIdentityProps } from './HomeIdentity'
import type { HomeTelemetryData } from './HomeTelemetry'
import { HomeTelemetryRail } from './HomeTelemetryRail'

export type HomeBriefingConversation = {
  ready: boolean
  canFollowUp: boolean
  session: BriefingSessionDetail | null
  isLoadingSession: boolean
  evidence: Omit<BriefingEvidenceState, 'sessionId'>
  onMarkPresented: (sessionId: string) => Promise<void>
  onOpenConversation: (conversationId: string) => void
}

export type HomeBriefingProps = {
  phase: BriefingLayoutPhase
  identity: HomeIdentityProps
  telemetry: HomeTelemetryData
  controls: BriefingProfilePanelProps
  conversation: HomeBriefingConversation
  onSelectView: (view: HomeActiveView) => void
  onReturnToStandby: () => void
}

function HomeAgentMessage({ text, metadata }: { text: string; metadata: Record<string, unknown> }): ReactElement {
  const toolOutputs = parseAgentQueryResponse({ ...metadata, answer: text }).tool_outputs ?? []
  return <>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    <CompactToolResults toolOutputs={toolOutputs} />
  </>
}

function BriefingConversation({ conversation }: { conversation: HomeBriefingConversation }): ReactElement {
  const { session, isLoadingSession, evidence, onMarkPresented } = conversation
  const renderAgent = useCallback((text: string, metadata: Record<string, unknown>): ReactNode => {
    if (session?.artifact && metadata.briefing_session_id === session.id) {
      return <BriefingArtifactMessage session={session} isLoadingSession={isLoadingSession} evidence={evidence} onMarkPresented={onMarkPresented} />
    }
    return <HomeAgentMessage text={text} metadata={metadata} />
  }, [evidence, isLoadingSession, onMarkPresented, session])
  if (!session) return <div className="flex min-h-0 flex-1 items-center justify-center p-5 text-xs text-zinc-500">Open a saved briefing to continue its conversation.</div>
  return <section className="flex min-h-0 flex-1 flex-col" aria-label="Briefing conversation">
    {conversation.ready ? (
      <ApexAssistantThread disabled={!conversation.canFollowUp} renderAgent={renderAgent} />
    ) : (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-5 text-center text-xs text-zinc-500">
        <p role="status">{isLoadingSession ? 'Loading saved conversation…' : 'This briefing conversation is not open yet.'}</p>
        {!isLoadingSession ? <button type="button" onClick={() => conversation.onOpenConversation(session.conversation_id)} className="text-[#A5C7FF] hover:text-white">Open conversation</button> : null}
      </div>
    )}
  </section>
}

export function HomeBriefing(props: HomeBriefingProps): ReactElement {
  const compact = useCompactLayout()
  const [compactPanel, setCompactPanel] = useState<'controls' | 'telemetry' | null>(null)
  const workspace = props.phase === 'workspace'
  const switcher = <HomeViewSwitcher view="briefing" onSelectView={props.onSelectView} onReturnToStandby={props.onReturnToStandby} />
  const controls = <BriefingProfilePanel {...props.controls} />

  if (compact) {
    const togglePanel = (panel: 'controls' | 'telemetry'): void => setCompactPanel((current) => current === panel ? null : panel)
    const showControls = !workspace || compactPanel === 'controls'
    return <section aria-label="Briefing" data-layout={workspace ? 'workspace' : 'identity'} className="flex w-full min-w-0 flex-col gap-3">
      <header className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-zinc-950/50 p-2.5 backdrop-blur-md">
        <HomeIdentityMark identity={props.identity} size="compact" />
        <div className="mr-auto">{switcher}</div>
        {workspace ? <button type="button" aria-expanded={compactPanel === 'controls'} aria-controls="home-briefing-controls" onClick={() => togglePanel('controls')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300">Controls</button> : null}
        <button type="button" aria-expanded={compactPanel === 'telemetry'} aria-controls="home-briefing-telemetry" onClick={() => togglePanel('telemetry')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300">Telemetry</button>
      </header>
      {showControls ? <div id="home-briefing-controls" className="rounded-xl border border-white/10 bg-zinc-950/60 p-3">{controls}</div> : null}
      {compactPanel === 'telemetry' ? <HomeTelemetryRail id="home-briefing-telemetry" data={props.telemetry} className="max-h-[70vh]" /> : null}
      {workspace ? <div className="flex min-h-[32rem] flex-col rounded-xl border border-white/10 bg-zinc-950/45"><BriefingConversation conversation={props.conversation} /></div> : null}
    </section>
  }

  if (!workspace) {
    return <section aria-label="Briefing" data-layout="identity" className="hud-home-layout-enter grid h-full min-h-0 w-full flex-1 grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)] gap-6">
      <div className="flex min-h-0 flex-col items-center justify-center gap-5 overflow-y-auto">
        <HomeIdentityMark identity={props.identity} size="large" />
        {switcher}
        <div className="w-full max-w-[40rem] rounded-xl border border-white/10 bg-zinc-950/55 p-3 backdrop-blur-md">{controls}</div>
      </div>
      <HomeTelemetryRail data={props.telemetry} />
    </section>
  }

  return <section aria-label="Briefing" data-layout="workspace" className="hud-home-layout-enter grid h-full min-h-0 w-full flex-1 grid-cols-[16rem_minmax(0,1fr)_20rem] gap-4">
    <aside className="flex min-h-0 flex-col items-center gap-4 overflow-y-auto rounded-xl border border-white/10 bg-zinc-950/45 p-3 scrollbar-thin" aria-label="Briefing identity and controls">
      <HomeIdentityMark identity={props.identity} size="compact" />
      {switcher}
      {controls}
    </aside>
    <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-zinc-950/45">
      <BriefingConversation conversation={props.conversation} />
    </div>
    <HomeTelemetryRail data={props.telemetry} />
  </section>
}
