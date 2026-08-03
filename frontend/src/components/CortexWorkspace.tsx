import { BrainCircuit, ExternalLink, Loader2, Plus } from 'lucide-react'
import { useEffect, useRef, useState, type ReactElement } from 'react'

import { type AgentMessage, type AgentQueryMetadata, type ToolTraceItem } from '../hooks/useCortex'
import type { AgentStatus, AgentKey, CloudEffort, LocalCommandStatus, LocalContextUsage, LocalToolScope, ToolOutputItem } from '../types/telemetry'

import { CortexToolCards } from './CortexToolCards'
import { AskApexBar } from './AskApexBar'
import { AgentSelector } from './AgentSelector'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'

interface CortexWorkspaceProps {
  activeAgent: AgentKey
  cloudEffort: CloudEffort
  askApexEnabled: boolean
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  history: AgentMessage[]
  latestTrace: ToolTraceItem[]
  error: string | null
  contextUsage: LocalContextUsage | null
  commands: LocalCommandStatus[]
  armedToolScope: LocalToolScope | null
  onArmedToolScopeChange: (scope: LocalToolScope | null) => void
  isQuerying: boolean
  lifecycleBusy: boolean
  lifecycleActionPending: boolean
  verifyingCloudAgent: AgentKey | null
  onLoadLocalModel: (agent: Extract<AgentKey, 'mus' | 'sorex'>) => Promise<boolean>
  onUnloadLocalModel: () => Promise<boolean>
  onVerifyCloudAgent: (agent: Exclude<AgentKey, 'mus' | 'sorex'>) => Promise<boolean>
  snapshotAttached: boolean
  snapshotAvailable: boolean
  onSnapshotAttachedChange: (attached: boolean) => void
  onAgentChange: (agent: AgentKey) => void
  onEffortChange: (effort: CloudEffort) => void
  onGoogleSearchChange: (enabled: boolean) => void
  onGoogleMapsChange: (enabled: boolean) => void
  onDelphinusXSearchChange: (enabled: boolean) => void
  onOrcinusXSearchChange: (enabled: boolean) => void
  onSubmit: (query: string, agent: AgentKey, toolScope?: LocalToolScope | null) => void
  onNewSession: () => void
}

function isLocalAgent(agent: AgentKey): agent is Extract<AgentKey, 'mus' | 'sorex'> {
  return agent === 'mus' || agent === 'sorex'
}

function formatNumber(value: number | null | undefined): string { return value == null ? 'â€”' : value.toLocaleString() }
function formatMilliseconds(value: number | null | undefined): string { return value == null ? 'â€”' : `${Math.round(value)} ms` }
function formatCurrency(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return 'â€”'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: value < 0.01 ? 5 : 2 }).format(value)
}

function TraceList({ trace }: { trace: ToolTraceItem[] }): ReactElement | null {
  if (trace.length === 0) return null
  return <section className="rounded-xl border border-white/10 bg-black/20 p-3" aria-label="Tool trace"><p className="mb-2 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Tool trace</p><ul className="space-y-1.5">{trace.map((item, index) => <li key={`${item.name}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-zinc-300"><span className={item.status.toLowerCase() === 'ok' ? 'text-emerald-300' : 'text-red-300'}>{item.status}</span><span>{item.name}</span>{item.origin ? <span className="text-zinc-500">{item.origin}</span> : null}{item.billable_units ? <span className="text-amber-200">{item.billable_units} billable</span> : null}<span className="ml-auto text-zinc-500">{formatMilliseconds(item.duration_ms)}</span></li>)}</ul></section>
}

function ResponseMetrics({ metadata }: { metadata: AgentQueryMetadata | undefined }): ReactElement | null {
  if (!metadata) return null
  const { agent, usage, timing, cost, citations } = metadata
  return <div className="mt-3 space-y-3">
    {agent ? <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-white/10 pt-3 font-mono text-[10px] text-zinc-500"><span>{agent.provider ?? 'provider'} / {agent.key}</span><span>{agent.resolvedModel ?? agent.configuredModel ?? 'model unavailable'}</span>{agent.resolvedEffort ? <span>{agent.resolvedEffort} effort</span> : null}{agent.version ? <span>v{agent.version}</span> : null}</div> : null}
    {usage || timing || cost ? <div className="grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3"><Metric label="Tokens" value={formatNumber(usage?.totalTokens)} detail={`in ${formatNumber(usage?.inputTokens)} Â· out ${formatNumber(usage?.outputTokens)} Â· reasoning ${formatNumber(usage?.reasoningTokens)}`} /><Metric label="Latency" value={formatMilliseconds(timing?.totalMs)} detail={`provider ${formatMilliseconds(timing?.providerMs)} Â· tools ${formatMilliseconds(timing?.apexToolMs)}`} /><Metric label="Estimate" value={formatCurrency(cost?.totalCost, cost?.currency)} detail={`tokens ${formatCurrency(cost?.tokenCost, cost?.currency)} Â· hosted ${formatCurrency(cost?.hostedToolCost, cost?.currency)}`} /></div> : null}
    {cost?.pricingVersion || cost?.completeness ? <p className="font-mono text-[10px] text-zinc-600">{cost.pricingVersion ?? 'pricing unavailable'} Â· {cost.completeness ?? 'estimate unavailable'}</p> : null}
    {citations.length > 0 ? <section className="space-y-1.5" aria-label="Citations"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Citations</p><ul className="space-y-1.5">{citations.map((citation, index) => <li key={`${citation.uri ?? citation.title ?? 'citation'}-${index}`} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-xs text-zinc-300">{citation.uri ? <a className="inline-flex items-center gap-1 text-[#7EB3FF] hover:text-white" href={citation.uri} target="_blank" rel="noreferrer"><span>{citation.title ?? citation.uri}</span><ExternalLink className="size-3" aria-hidden /></a> : <span>{citation.title ?? citation.source ?? 'Grounding source'}</span>}{citation.snippet ? <p className="mt-1 text-zinc-500">{citation.snippet}</p> : null}</li>)}</ul></section> : null}
  </div>
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }): ReactElement {
  return <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5"><p className="font-mono uppercase tracking-wider text-zinc-500">{label}</p><p className="mt-1 font-mono text-zinc-200">{value}</p><p className="mt-1 text-zinc-500">{detail}</p></div>
}

function Conversation({ history, latestTrace, error, isQuerying, agentsStatus, activeAgent, onPromptSelect }: { history: AgentMessage[]; latestTrace: ToolTraceItem[]; error: string | null; isQuerying: boolean; agentsStatus: AgentStatus[]; activeAgent: AgentKey; onPromptSelect: ((query: string) => void) | null }): ReactElement {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const target = endRef.current
    if (typeof target?.scrollIntoView === 'function') target.scrollIntoView({ behavior: 'smooth' })
  }, [history, isQuerying])
  const agentName = agentsStatus.find((agent) => agent.key === activeAgent)?.display_name ?? 'APEX'
  return <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 scrollbar-thin" aria-live="polite">
    {history.length === 0 && !isQuerying ? <div className="flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 text-center"><p className="font-mono text-xs uppercase tracking-widest text-zinc-500">APEX is ready. Start a session with a focused question.</p>{onPromptSelect ? <div className="mt-4 flex max-w-xl flex-wrap justify-center gap-2">{OPERATION_PROMPT_CHIPS.map((chip) => <button key={chip.label} type="button" onClick={() => onPromptSelect(chip.query)} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 transition-colors hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]">{chip.label}</button>)}</div> : null}</div> : null}
    {history.map((message, index) => {
      if (message.role === 'user') return <div key={`user-${index}`} className="flex justify-end"><p className="max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/35 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white">{message.content}</p></div>
      if (message.role !== 'agent') return null
      const toolOutputs: ToolOutputItem[] = message.tool_outputs ?? []
      return <div key={`agent-${index}`} className="max-w-5xl"><div className="rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3"><p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{message.metadata?.agent?.key ?? agentName}</p><div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">{message.content}</div><TraceList trace={message.tool_trace ?? (index === history.length - 1 ? latestTrace : [])} /><ResponseMetrics metadata={message.metadata} /></div>{toolOutputs.length > 0 ? <CortexToolCards toolOutputs={toolOutputs} /> : null}</div>
    })}
    {error ? <p className="rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-2 text-sm text-red-200" role="alert">{error}</p> : null}
    {isQuerying ? <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-[#D8B4FE]"><Loader2 className="size-4 animate-spin" aria-hidden />{agentName} working</div> : null}
    <div ref={endRef} />
  </div>
}

function LocalToolScopes({ commands, armedToolScope, contextUsage, onChange }: { commands: LocalCommandStatus[]; armedToolScope: LocalToolScope | null; contextUsage: LocalContextUsage | null; onChange: (scope: LocalToolScope | null) => void }): ReactElement {
  const promptTokens = contextUsage ? contextUsage.peak_prompt_tokens ?? contextUsage.estimated_prompt_tokens : null
  return <section className="space-y-2" aria-label="Local tool scopes"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Local tool scopes</p>{armedToolScope ? <p className="rounded-md border border-orange-400/20 bg-orange-950/20 px-2 py-1 font-mono text-[10px] text-orange-200">/{armedToolScope} armed for next request</p> : <p className="font-mono text-[10px] text-zinc-500">No scope armed for the next request.</p>}<div className="space-y-1">{commands.length === 0 ? <p className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-xs text-zinc-500">Checking command availabilityâ€¦</p> : commands.map((command) => { const armed = armedToolScope === command.key; return <button key={command.key} type="button" disabled={!command.available} aria-pressed={armed} title={command.unavailable_reason ?? undefined} onClick={() => onChange(armed ? null : command.key)} className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors ${armed ? 'border-orange-400/45 bg-orange-950/25' : 'border-white/10 bg-white/[0.02] hover:border-white/25'} disabled:cursor-not-allowed disabled:opacity-45`}><span className="w-[4.75rem] shrink-0 font-mono text-[10px] text-[#7EB3FF]">{command.command}</span><span className="min-w-0 flex-1"><span className="block text-[11px] text-zinc-300">{command.description}</span>{!command.available && command.unavailable_reason ? <span className="block text-[10px] text-red-200">{command.unavailable_reason}</span> : null}</span><span className="shrink-0 text-right font-mono text-[9px] text-zinc-500">{command.tool_count} tools<br />~{command.estimated_schema_tokens}</span></button> })}</div>{contextUsage && promptTokens !== null ? <div className="rounded-lg border border-white/10 bg-black/20 p-2.5 font-mono text-[11px] text-zinc-400"><div className="flex justify-between"><span>Local context</span><span className={promptTokens / contextUsage.context_window >= 0.8 ? 'text-amber-400' : ''}>{formatNumber(promptTokens)}/{formatNumber(contextUsage.context_window)}</span></div><p className="mt-1 text-zinc-600">{contextUsage.history_messages_dropped} messages trimmed</p></div> : null}</section>
}

function formatCountdown(seconds: number | null): string {
  if (seconds === null) return '--:--'
  const safe = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}

function useIdleUnloadCountdown(seconds: number | null, running: boolean): number | null {
  const [remaining, setRemaining] = useState(seconds)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Status polling is authoritative and must resynchronize the local display before its next tick.
    setRemaining(seconds)
    if (seconds === null || !running) return
    const intervalId = window.setInterval(() => {
      setRemaining((current) => current === null ? null : Math.max(0, current - 1))
    }, 1_000)
    return () => window.clearInterval(intervalId)
  }, [running, seconds])

  return remaining
}

function LocalModelLifecycle({ agent, busy, actionPending, onLoad, onUnload }: { agent: AgentStatus; busy: boolean; actionPending: boolean; onLoad: (agent: Extract<AgentKey, 'mus' | 'sorex'>) => Promise<boolean>; onUnload: () => Promise<boolean> }): ReactElement {
  const [error, setError] = useState<string | null>(null)
  const transition = agent.loading || actionPending
  const lifecycleState = agent.loading ? 'Loading' : agent.active ? 'Loaded' : agent.status === 'available' ? 'Unloaded' : 'Unavailable'
  const canUnload = lifecycleState === 'Loaded'
  const disabled = busy || transition || lifecycleState === 'Unavailable'
  const idleUnloadRemaining = useIdleUnloadCountdown(
    agent.idle_unload_remaining_seconds,
    lifecycleState === 'Loaded' && !busy && !transition,
  )
  const actionLabel = canUnload ? 'Unload model' : 'Load model'
  const stateClassName = lifecycleState === 'Unavailable'
    ? 'border-red-400/35 bg-red-950/20 text-red-200'
    : lifecycleState === 'Loaded'
      ? 'border-orange-400/40 bg-orange-950/30 text-orange-100'
      : 'border-amber-400/35 bg-amber-950/20 text-amber-100'
  const action = async (): Promise<void> => {
    if (disabled) return
    setError(null)
    const successful = canUnload ? await onUnload() : await onLoad(agent.key as Extract<AgentKey, 'mus' | 'sorex'>)
    if (!successful) setError(`${canUnload ? 'Unload' : 'Load'} failed. Check Ollama status and try again.`)
  }
  if (lifecycleState === 'Loaded') {
    return <section className="space-y-2" aria-label="Local model lifecycle">
      <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Local model</p>
      <div className="rounded-lg border border-orange-500/25 bg-orange-950/10 p-3">
        <div className="flex items-center justify-between gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${stateClassName}`} aria-live="polite"><span className="size-1.5 rounded-full bg-current" aria-hidden />{lifecycleState}</span><span className="font-mono text-[10px] text-zinc-500">{agent.configured_model}</span></div>
        <button type="button" disabled={disabled} onClick={() => void action()} className="mt-3 inline-flex w-full items-center justify-center rounded-md border border-orange-400/40 bg-orange-950/25 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-orange-100 transition-colors hover:border-orange-300 hover:bg-orange-950/45 disabled:cursor-not-allowed disabled:opacity-45">{transition ? <Loader2 className="cortex-lifecycle-spinner mr-1.5 size-3.5" aria-hidden /> : null}{transition ? 'Unloadingâ€¦' : actionLabel}</button>
        <p className="mt-2 font-mono text-[10px] text-orange-100/75" aria-live="polite">{busy ? 'In use Â· auto-unload paused' : `Auto-unload in ${formatCountdown(idleUnloadRemaining)}`}</p>
        <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">Loading pre-warms this agent; normal requests can still load it when needed. Unloading frees memory without changing the selected agent.</p>
        {busy ? <p className="mt-1 text-[10px] text-amber-200">Lifecycle actions are unavailable while local inference is active.</p> : null}
        {error ? <p className="mt-1 text-[10px] text-red-200" role="alert">{error}</p> : null}
      </div>
    </section>
  }
  return <section className="space-y-2" aria-label="Local model lifecycle"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Local model</p><div className="rounded-lg border border-orange-500/25 bg-orange-950/10 p-3"><div className="flex items-center justify-between gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${stateClassName}`} aria-live="polite"><span className={`size-1.5 rounded-full bg-current ${transition ? 'cortex-lifecycle-status--transitioning' : ''}`} aria-hidden />{lifecycleState}</span><span className="font-mono text-[10px] text-zinc-500">{agent.configured_model}</span></div><button type="button" disabled={disabled} onClick={() => void action()} className="mt-3 inline-flex w-full items-center justify-center rounded-md border border-orange-400/40 bg-orange-950/25 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-orange-100 transition-colors hover:border-orange-300 hover:bg-orange-950/45 disabled:cursor-not-allowed disabled:opacity-45">{transition ? <Loader2 className="cortex-lifecycle-spinner mr-1.5 size-3.5" aria-hidden /> : null}{transition ? (canUnload ? 'Unloadingâ€¦' : 'Loadingâ€¦') : actionLabel}</button><p className="mt-2 text-[11px] leading-relaxed text-zinc-500">Loading pre-warms this agent; normal requests can still load it when needed. Unloading frees memory without changing the selected agent.</p>{!agent.active && lifecycleState === 'Unloaded' ? <p className="mt-1 text-[10px] text-zinc-600">Loading this agent may replace another resident local model.</p> : null}{busy ? <p className="mt-1 text-[10px] text-amber-200">Lifecycle actions are unavailable while local inference is active.</p> : null}{agent.reason && lifecycleState === 'Unavailable' ? <p className="mt-1 text-[10px] text-red-200">{agent.reason}</p> : null}{error ? <p className="mt-1 text-[10px] text-red-200" role="alert">{error}</p> : null}</div></section>
}

export function CortexWorkspace(props: CortexWorkspaceProps): ReactElement {
  const local = isLocalAgent(props.activeAgent)
  const activeStatus = props.agentsStatus.find((agent) => agent.key === props.activeAgent)
  return <section className="relative z-[var(--z-bento-hud)] mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-zinc-950/45 shadow-2xl backdrop-blur-xl" aria-label="Cortex workspace">
    <header className="flex flex-wrap items-center gap-3 border-b border-white/10 bg-black/20 px-4 py-3 sm:px-5"><div className="mr-auto flex items-center gap-2"><span className="hud-icon-badge size-8 text-[#C084FC]"><BrainCircuit className="size-4" aria-hidden /></span><div><h1 className="font-orbitron text-sm font-semibold uppercase tracking-[0.16em] text-white">Cortex</h1><p className="font-mono text-[10px] text-zinc-500">Operate and configure Apex Agents</p></div></div><button type="button" onClick={props.onNewSession} disabled={props.isQuerying} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:text-white disabled:opacity-40"><Plus className="size-3.5" aria-hidden />New session</button></header>
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem]"><div className="order-1 flex min-h-0 flex-col"><Conversation history={props.history} latestTrace={props.latestTrace} error={props.error} isQuerying={props.isQuerying} agentsStatus={props.agentsStatus} activeAgent={props.activeAgent} onPromptSelect={props.askApexEnabled ? (query) => props.onSubmit(query, props.activeAgent) : null} />{props.askApexEnabled ? <footer className="border-t border-white/10 bg-black/20 p-3 sm:p-4"><AskApexBar presentation="cortex" activeAgent={props.activeAgent} onSubmit={props.onSubmit} agentsStatus={props.agentsStatus} commands={local ? props.commands : []} armedToolScope={local ? props.armedToolScope : null} onArmedToolScopeChange={props.onArmedToolScopeChange} isSubmitting={props.isQuerying} error={props.error} /></footer> : <footer className="border-t border-white/10 p-4 text-sm text-zinc-500">Ask APEX is disabled in Settings.</footer>}</div>
      <aside className="order-2 space-y-4 border-t border-white/10 bg-black/15 p-4 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:border-t-0 scrollbar-thin" aria-label="Cortex inspector"><section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Agent</p><AgentSelector activeAgent={props.activeAgent} onChange={props.onAgentChange} agentsStatus={props.agentsStatus} agentsStatusHydrated={props.agentsStatusHydrated} isQuerying={props.isQuerying} verifyingAgent={props.verifyingCloudAgent} onVerify={props.onVerifyCloudAgent} /></section>
        {!local ? <CloudControls {...props} /> : null}
        {local && activeStatus ? <><LocalModelLifecycle agent={activeStatus} busy={props.lifecycleBusy} actionPending={props.lifecycleActionPending} onLoad={props.onLoadLocalModel} onUnload={props.onUnloadLocalModel} /><LocalToolScopes commands={props.commands} armedToolScope={props.armedToolScope} contextUsage={props.contextUsage} onChange={props.onArmedToolScopeChange} /></> : null}
        <ContextControl {...props} />
      </aside>
    </div>
  </section>
}

function CloudControls(props: CortexWorkspaceProps): ReactElement {
  const activeAgent = props.agentsStatus.find((agent) => agent.key === props.activeAgent)
  const effortOptions = activeAgent?.effort_options ?? []
  const grounding = props.activeAgent === 'neofelis'
    ? <GroundingControls label="Neofelis" note="Apex Brave Search remains the standard search capability when connected."><GroundingToggle label="Google Search" detail="Provider grounding for later requests" checked={activeAgent?.native_tools.google_search ?? false} onChange={props.onGoogleSearchChange} /><GroundingToggle label="Google Maps" detail="Provider grounding for later requests" checked={activeAgent?.native_tools.google_maps ?? false} onChange={props.onGoogleMapsChange} /></GroundingControls>
    : props.activeAgent === 'delphinus' || props.activeAgent === 'orcinus'
      ? <GroundingControls label={props.activeAgent === 'delphinus' ? 'Delphinus' : 'Orcinus'} note="Apex Brave Search remains the standard search capability when connected."><GroundingToggle label="X Search" detail="Provider grounding for later requests" checked={activeAgent?.native_tools.x_search ?? false} onChange={props.activeAgent === 'delphinus' ? props.onDelphinusXSearchChange : props.onOrcinusXSearchChange} /></GroundingControls>
      : null
  return <>{effortOptions.length > 0 ? <section className="space-y-2"><label htmlFor="cortex-effort" className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Reasoning effort</label><select id="cortex-effort" value={props.cloudEffort} onChange={(event) => props.onEffortChange(event.target.value as CloudEffort)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF]">{effortOptions.map((effort) => <option key={effort} value={effort}>{effort.slice(0, 1).toUpperCase()}{effort.slice(1)}</option>)}</select></section> : null}{grounding}</>
}

function ContextControl(props: CortexWorkspaceProps): ReactElement { return <section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Context</p><label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span className="text-xs text-zinc-300">Current HUD snapshot</span><input type="checkbox" checked={props.snapshotAttached} disabled={!props.snapshotAvailable} onChange={(event) => props.onSnapshotAttachedChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label><p className="text-[11px] leading-relaxed text-zinc-500">{props.snapshotAttached && props.snapshotAvailable ? 'The current snapshot will be included with the next turn.' : 'No HUD context will be attached.'}</p></section> }
function GroundingToggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (enabled: boolean) => void }): ReactElement { return <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span><span className="block font-mono text-[10px] uppercase tracking-wider text-zinc-300">{label}</span><span className="block text-[11px] text-zinc-500">{detail} Â· {checked ? 'Enabled' : 'Disabled'}</span></span><input aria-label={`${label} grounding`} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label> }
function GroundingControls({ label, note, children }: { label: string; note: string; children: ReactElement | ReactElement[] }): ReactElement { return <section className="space-y-2" aria-label={`${label} grounding`}><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Grounding</p>{children}<p className="text-[11px] leading-relaxed text-zinc-500">{note}</p></section> }
