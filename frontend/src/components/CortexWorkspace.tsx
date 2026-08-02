import { BrainCircuit, ExternalLink, Loader2, Plus } from 'lucide-react'
import { useEffect, useRef, type ReactElement } from 'react'

import {
  type AgentMessage,
  type AssistantQueryMetadata,
  type ToolTraceItem,
} from '../hooks/useApexAssistant'
import type {
  AgentProfileStatus,
  AssistantMode,
  AssistantProfile,
  CloudEffort,
  LocalContextUsage,
  LocalToolScope,
  ToolOutputItem,
} from '../types/telemetry'

import { AssistantToolCards } from './AssistantToolCards'
import { AskApexBar } from './AskApexBar'
import { ProfileCardSelector } from './ProfileCardSelector'

interface CortexWorkspaceProps {
  activeProfile: AssistantProfile
  cloudEffort: CloudEffort
  devModeActive: boolean
  askApexEnabled: boolean
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  history: AgentMessage[]
  latestTrace: ToolTraceItem[]
  error: string | null
  contextUsage: LocalContextUsage | null
  isQuerying: boolean
  snapshotAttached: boolean
  snapshotAvailable: boolean
  onSnapshotAttachedChange: (attached: boolean) => void
  onProfileChange: (profile: AssistantProfile) => void
  onModeChange: (mode: AssistantMode) => void
  onEffortChange: (effort: CloudEffort) => void
  onGoogleSearchChange: (enabled: boolean) => void
  neofelisGoogleSearchEnabled: boolean
  onGoogleMapsChange: (enabled: boolean) => void
  neofelisGoogleMapsEnabled: boolean
  onDelphinusXSearchChange: (enabled: boolean) => void
  delphinusXSearchEnabled: boolean
  onOrcinusXSearchChange: (enabled: boolean) => void
  orcinusXSearchEnabled: boolean
  onSubmit: (query: string, profile: AssistantProfile, toolScope?: LocalToolScope | null) => void
  onNewSession: () => void
}

function profileMode(profile: AssistantProfile): AssistantMode {
  return profile === 'mus' || profile === 'sorex' ? 'local' : 'cloud'
}

function formatNumber(value: number | null | undefined): string {
  return value == null ? '—' : value.toLocaleString()
}

function formatMilliseconds(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)} ms`
}

function formatCurrency(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: value < 0.01 ? 5 : 2,
  }).format(value)
}

function TraceList({ trace }: { trace: ToolTraceItem[] }): ReactElement | null {
  if (trace.length === 0) return null
  return (
    <section className="rounded-xl border border-white/10 bg-black/20 p-3" aria-label="Tool trace">
      <p className="mb-2 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Tool trace</p>
      <ul className="space-y-1.5">
        {trace.map((item, index) => (
          <li key={`${item.name}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-zinc-300">
            <span className={item.status.toLowerCase() === 'ok' ? 'text-emerald-300' : 'text-red-300'}>{item.status}</span>
            <span>{item.name}</span>
            {item.origin ? <span className="text-zinc-500">{item.origin}</span> : null}
            {item.billable_units ? <span className="text-amber-200">{item.billable_units} billable</span> : null}
            <span className="ml-auto text-zinc-500">{formatMilliseconds(item.duration_ms)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ResponseMetrics({ metadata }: { metadata: AssistantQueryMetadata | undefined }): ReactElement | null {
  if (!metadata) return null
  const { profile, usage, timing, cost, citations } = metadata
  return (
    <div className="mt-3 space-y-3">
      {profile ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-white/10 pt-3 font-mono text-[10px] text-zinc-500">
          <span>{profile.provider ?? 'provider'} / {profile.key}</span>
          <span>{profile.resolvedModel ?? profile.configuredModel ?? 'model unavailable'}</span>
          {profile.resolvedEffort ? <span>{profile.resolvedEffort} effort</span> : null}
          {profile.version ? <span>v{profile.version}</span> : null}
        </div>
      ) : null}
      {usage || timing || cost ? (
        <div className="grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3">
          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
            <p className="font-mono uppercase tracking-wider text-zinc-500">Tokens</p>
            <p className="mt-1 font-mono text-zinc-200">{formatNumber(usage?.totalTokens)}</p>
            <p className="mt-1 text-zinc-500">in {formatNumber(usage?.inputTokens)} · out {formatNumber(usage?.outputTokens)} · reasoning {formatNumber(usage?.reasoningTokens)}</p>
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
            <p className="font-mono uppercase tracking-wider text-zinc-500">Latency</p>
            <p className="mt-1 font-mono text-zinc-200">{formatMilliseconds(timing?.totalMs)}</p>
            <p className="mt-1 text-zinc-500">provider {formatMilliseconds(timing?.providerMs)} · tools {formatMilliseconds(timing?.apexToolMs)}</p>
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
            <p className="font-mono uppercase tracking-wider text-zinc-500">Estimate</p>
            <p className="mt-1 font-mono text-zinc-200">{formatCurrency(cost?.totalCost, cost?.currency)}</p>
            <p className="mt-1 text-zinc-500">tokens {formatCurrency(cost?.tokenCost, cost?.currency)} · hosted {formatCurrency(cost?.hostedToolCost, cost?.currency)}</p>
          </div>
        </div>
      ) : null}
      {cost?.pricingVersion || cost?.completeness ? <p className="font-mono text-[10px] text-zinc-600">{cost.pricingVersion ?? 'pricing unavailable'} · {cost.completeness ?? 'estimate unavailable'}</p> : null}
      {citations.length > 0 ? (
        <section className="space-y-1.5" aria-label="Citations">
          <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Citations</p>
          <ul className="space-y-1.5">
            {citations.map((citation, index) => (
              <li key={`${citation.uri ?? citation.title ?? 'citation'}-${index}`} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-xs text-zinc-300">
                {citation.uri ? <a className="inline-flex items-center gap-1 text-[#7EB3FF] hover:text-white" href={citation.uri} target="_blank" rel="noreferrer"><span>{citation.title ?? citation.uri}</span><ExternalLink className="size-3" aria-hidden /></a> : <span>{citation.title ?? citation.source ?? 'Grounding source'}</span>}
                {citation.snippet ? <p className="mt-1 text-zinc-500">{citation.snippet}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}

function Conversation({ history, latestTrace, error, isQuerying, profilesStatus, activeProfile }: {
  history: AgentMessage[]
  latestTrace: ToolTraceItem[]
  error: string | null
  isQuerying: boolean
  profilesStatus: AgentProfileStatus[]
  activeProfile: AssistantProfile
}): ReactElement {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const target = endRef.current
    if (typeof target?.scrollIntoView === 'function') {
      target.scrollIntoView({ behavior: 'smooth' })
    }
  }, [history, isQuerying])
  const profileName = profilesStatus.find((profile) => profile.key === activeProfile)?.display_name ?? 'APEX'
  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 scrollbar-thin" aria-live="polite">
      {history.length === 0 && !isQuerying ? <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-white/10 px-6 text-center font-mono text-xs uppercase tracking-widest text-zinc-500">Cortex is ready. Start a session with a focused question.</div> : null}
      {history.map((message, index) => {
        if (message.role === 'user') return <div key={`user-${index}`} className="flex justify-end"><p className="max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/35 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white">{message.content}</p></div>
        if (message.role !== 'model') return null
        const toolOutputs: ToolOutputItem[] = message.tool_outputs ?? []
        return <div key={`model-${index}`} className="max-w-5xl"><div className="rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3"><p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{message.metadata?.profile?.key ?? profileName}</p><div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">{message.content}</div><TraceList trace={message.tool_trace ?? (index === history.length - 1 ? latestTrace : [])} /><ResponseMetrics metadata={message.metadata} /></div>{toolOutputs.length > 0 ? <AssistantToolCards toolOutputs={toolOutputs} /> : null}</div>
      })}
      {error ? <p className="rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-2 text-sm text-red-200" role="alert">{error}</p> : null}
      {isQuerying ? <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-[#D8B4FE]"><Loader2 className="size-4 animate-spin" aria-hidden />{profileName} working</div> : null}
      <div ref={endRef} />
    </div>
  )
}

export function CortexWorkspace(props: CortexWorkspaceProps): ReactElement {
  const mode = profileMode(props.activeProfile)
  return (
    <section className="relative z-[var(--z-bento-hud)] mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-zinc-950/45 shadow-2xl backdrop-blur-xl" aria-label="Cortex workspace">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 bg-black/20 px-4 py-3 sm:px-5">
        <div className="mr-auto flex items-center gap-2"><span className="hud-icon-badge size-8 text-[#C084FC]"><BrainCircuit className="size-4" aria-hidden /></span><div><h1 className="font-orbitron text-sm font-semibold uppercase tracking-[0.16em] text-white">Cortex</h1><p className="font-mono text-[10px] text-zinc-500">Independent operations workspace</p></div></div>
        <button type="button" onClick={props.onNewSession} disabled={props.isQuerying} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:text-white disabled:opacity-40"><Plus className="size-3.5" aria-hidden />New session</button>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="order-1 flex min-h-0 flex-col"><Conversation history={props.history} latestTrace={props.latestTrace} error={props.error} isQuerying={props.isQuerying} profilesStatus={props.profilesStatus} activeProfile={props.activeProfile} />{props.askApexEnabled ? <footer className="border-t border-white/10 bg-black/20 p-3 sm:p-4"><AskApexBar activeProfile={props.activeProfile} onSubmit={props.onSubmit} profilesStatus={props.profilesStatus} isSubmitting={props.isQuerying} showCommands contextUsage={props.contextUsage} integrated /></footer> : <footer className="border-t border-white/10 p-4 text-sm text-zinc-500">Ask APEX is disabled in Settings.</footer>}</div>
        <aside className="order-2 space-y-4 border-t border-white/10 bg-black/15 p-4 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:border-t-0 scrollbar-thin" aria-label="Cortex inspector">
          <section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Profile</p><ProfileCardSelector activeProfile={props.activeProfile} onChange={props.onProfileChange} onModeChange={props.onModeChange} profilesStatus={props.profilesStatus} profilesStatusHydrated={props.profilesStatusHydrated} devModeActive={props.devModeActive} /></section>
          {mode === 'cloud' ? <section className="space-y-2"><label htmlFor="cortex-effort" className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Reasoning effort</label><select id="cortex-effort" value={props.activeProfile === 'acinonyx' ? 'focused' : props.cloudEffort} onChange={(event) => props.onEffortChange(event.target.value as CloudEffort)} disabled={props.activeProfile === 'acinonyx'} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF] disabled:opacity-50"><option value="light">Light</option><option value="focused">Focused</option><option value="extended">Extended</option></select>{props.activeProfile === 'acinonyx' ? <p className="text-[11px] text-zinc-500">Acinonyx is fixed to Focused in the sandbox.</p> : null}</section> : null}
          {props.activeProfile === 'neofelis' ? <GroundingControls label="Neofelis" note="Apex Brave Search remains the standard search capability when connected."><GroundingToggle label="Google Search" detail="Provider grounding for later requests" checked={props.neofelisGoogleSearchEnabled} onChange={props.onGoogleSearchChange} /><GroundingToggle label="Google Maps" detail="Provider grounding for later requests" checked={props.neofelisGoogleMapsEnabled} onChange={props.onGoogleMapsChange} /></GroundingControls> : null}
          {props.activeProfile === 'delphinus' ? <GroundingControls label="Delphinus" note="Apex Brave Search remains the standard search capability when connected."><GroundingToggle label="X Search" detail="Provider grounding for later requests" checked={props.delphinusXSearchEnabled} onChange={props.onDelphinusXSearchChange} /></GroundingControls> : null}
          {props.activeProfile === 'orcinus' ? <GroundingControls label="Orcinus" note="Apex Brave Search remains the standard search capability when connected."><GroundingToggle label="X Search" detail="Provider grounding for later requests" checked={props.orcinusXSearchEnabled} onChange={props.onOrcinusXSearchChange} /></GroundingControls> : null}
          <section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Context</p><label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span className="text-xs text-zinc-300">Current HUD snapshot</span><input type="checkbox" checked={props.snapshotAttached} disabled={!props.snapshotAvailable} onChange={(event) => props.onSnapshotAttachedChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label><p className="text-[11px] leading-relaxed text-zinc-500">{props.snapshotAttached && props.snapshotAvailable ? 'The current snapshot will be included with the next turn.' : 'No HUD context will be attached.'}</p>{props.contextUsage ? <div className="rounded-lg border border-white/10 bg-black/20 p-2.5 font-mono text-[11px] text-zinc-400"><div className="flex justify-between"><span>Local context</span><span>{formatNumber(props.contextUsage.peak_prompt_tokens ?? props.contextUsage.estimated_prompt_tokens)}/{formatNumber(props.contextUsage.context_window)}</span></div><p className="mt-1 text-zinc-600">{props.contextUsage.history_messages_dropped} messages trimmed</p></div> : null}</section>
        </aside>
      </div>
    </section>
  )
}

function GroundingToggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (enabled: boolean) => void }): ReactElement {
  return <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span><span className="block font-mono text-[10px] uppercase tracking-wider text-zinc-300">{label}</span><span className="block text-[11px] text-zinc-500">{detail} · {checked ? 'Enabled' : 'Disabled'}</span></span><input aria-label={`${label} grounding`} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label>
}

function GroundingControls({ label, note, children }: { label: string; note: string; children: ReactElement | ReactElement[] }): ReactElement {
  return <section className="space-y-2" aria-label={`${label} grounding`}><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Grounding</p>{children}<p className="text-[11px] leading-relaxed text-zinc-500">{note}</p></section>
}
