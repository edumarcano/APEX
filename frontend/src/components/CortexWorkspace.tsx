import { BrainCircuit, ExternalLink, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactElement } from 'react'

import { parseAgentQueryResponse, type AgentQueryMetadata, type ToolTraceItem } from '../lib/cortexResponse'
import type { UseActionsResult } from '../hooks/useActions'
import type {
  AgentStatus,
  AgentKey,
  CloudEffort,
  HostedTool,
  LocalContextUsage,
  LocalReasoningMode,
  ToolCatalog,
  ToolPreflightEstimate,
  SystemDiagnostics,
} from '../types/telemetry'
import type { CloudHostedToolsSettings } from '../types/settings'
import {
  formatContextWindowLabel,
  formatReasoningLabel,
  hostedCapabilitiesForModel,
  providerDisplayName,
  resolveModelCatalog,
} from '../lib/agents'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CortexToolCards } from './CortexToolCards'
import { CortexActions } from './CortexActions'
import { CortexContext } from './CortexContext'
import { CortexActivity } from './CortexActivity'
import { CortexActiveRunStrip } from './CortexActiveRunStrip'
import { type ApexLogoProps } from './ApexLogo'
import { ModelSelector } from './ModelSelector'
import { ApexAssistantThread, ApexConversationRail, type ApexAssistantComposerProps, type ApexAssistantRunConfig } from './ApexAssistantRuntime'
import { useContextInspector } from '../hooks/useContextInspector'
import { useCortexRuns } from '../hooks/useCortexRuns'

const INSPECTOR_TABS = ['controls', 'context', 'actions', 'activity'] as const

interface CortexWorkspaceProps {
  activeAgent: AgentKey
  cloudEffort: CloudEffort
  selectedModel?: string
  localContextWindow: number
  localReasoningMode: LocalReasoningMode
  hostedTools?: CloudHostedToolsSettings
  devModeActive: boolean
  sandboxMode: boolean
  agentQueriesEnabled: boolean
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  latestTrace: ToolTraceItem[]
  error: string | null
  contextUsage: LocalContextUsage | null
  toolCatalog?: ToolCatalog | null
  selectedToolNames?: string[]
  activeToolProfileId?: string | null
  selectionReady?: boolean
  submissionPending?: boolean
  conversationHydrating?: boolean
  onToolSelectionChange?: (names: string[]) => void
  onToolProfileChange?: (profileId: string) => void
  toolPreflight?: ToolPreflightEstimate | null
  toolPreflightLoading?: boolean
  toolCatalogError?: string | null
  toolPreflightError?: string | null
  toolProfileFeedback?: string | null
  toolProfileError?: string | null
  onSaveToolProfile?: (name: string) => void
  onDuplicateToolProfile?: (profileId: string, name: string) => void
  onRenameToolProfile?: (profileId: string, name: string) => void
  onDeleteToolProfile?: (profileId: string) => void
  onRestoreToolProfile?: (profileId: string) => void
  onSetDefaultToolProfile?: (profileId: string) => void
  isQuerying: boolean
  logoProps: Omit<ApexLogoProps, 'className'>
  lifecycleBusy: boolean
  lifecycleActionPending: boolean
  verifyingCloudModel?: string | null
  onLoadLocalModel: (modelId: string) => Promise<boolean>
  onUnloadLocalModel: () => Promise<boolean>
  onVerifyCloudAgent: (modelId: string) => Promise<boolean>
  snapshotAttached: boolean
  snapshotAvailable: boolean
  personalContextEnabled?: boolean
  onPersonalContextEnabledChange?: (enabled: boolean) => Promise<boolean>
  onSnapshotAttachedChange: (attached: boolean) => void
  onModelChange?: (model: string) => void
  onEffortChange: (effort: CloudEffort) => void
  onHostedToolChange: (tool: HostedTool, enabled: boolean) => void
  onSandboxModeChange: (enabled: boolean) => void
  onLocalContextWindowChange: (contextWindow: number) => Promise<boolean>
  onLocalReasoningModeChange: (reasoningMode: LocalReasoningMode) => Promise<boolean>
  actions: UseActionsResult
  demoModeActive: boolean
  assistantRunConfig: ApexAssistantRunConfig
  onAssistantPreflight?: (config: ApexAssistantRunConfig) => Promise<boolean>
  diagnostics?: SystemDiagnostics | null
}

function LocalContextControl({
  agent,
  disabled,
  onChange,
}: {
  agent: AgentStatus
  disabled: boolean
  onChange: (contextWindow: number) => Promise<boolean>
}): ReactElement {
  const options = agent.context_window_options ?? []
  const authoritativeContextWindow =
    agent.context_window ?? agent.default_context_window ?? options[0]
  const [selectedContextWindow, setSelectedContextWindow] = useState(
    authoritativeContextWindow,
  )
  const [pendingTarget, setPendingTarget] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (pendingTarget !== null) {
      if (authoritativeContextWindow === pendingTarget) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Clear the write barrier once refreshed authority matches the optimistic selection.
        setPendingTarget(null)
        setSelectedContextWindow(authoritativeContextWindow)
      }
      return
    }
    setSelectedContextWindow(authoritativeContextWindow)
  }, [authoritativeContextWindow, pendingTarget])
  const handleChange = async (contextWindow: number): Promise<void> => {
    const rollbackContextWindow =
      pendingTarget ?? authoritativeContextWindow
    setSelectedContextWindow(contextWindow)
    setPendingTarget(contextWindow)
    setSaving(true)
    try {
      const persisted = await onChange(contextWindow)
      if (!persisted) {
        setPendingTarget(null)
        setSelectedContextWindow(rollbackContextWindow)
      }
    } catch {
      setPendingTarget(null)
      setSelectedContextWindow(rollbackContextWindow)
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="space-y-2" aria-label={`${agent.display_name} context window`}>
      <label htmlFor={`cortex-${agent.key}-context`} className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">
        Context window
      </label>
      <select
        id={`cortex-${agent.key}-context`}
        value={String(selectedContextWindow ?? '')}
        disabled={disabled || saving}
        onChange={(event) => {
          void handleChange(Number(event.target.value))
        }}
        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {formatContextWindowLabel(option) ?? String(option)}
            {agent.context_window_high_resource_options?.includes(option)
              ? ' High resource'
              : ''}
          </option>
        ))}
      </select>
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Applies the next time {agent.display_name} loads. Unload {agent.display_name} first to
        switch context on a resident model.
      </p>
    </section>
  )
}

function LocalReasoningControl({
  agent,
  disabled,
  onChange,
}: {
  agent: AgentStatus
  disabled: boolean
  onChange: (reasoningMode: LocalReasoningMode) => Promise<boolean>
}): ReactElement {
  const options = agent.reasoning_mode_options ?? []
  const authoritativeReasoningMode =
    agent.reasoning_mode ?? agent.default_reasoning_mode ?? options[0]
  const [selectedReasoningMode, setSelectedReasoningMode] = useState(
    authoritativeReasoningMode,
  )
  const [pendingTarget, setPendingTarget] = useState<LocalReasoningMode | null>(
    null,
  )
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (pendingTarget !== null) {
      if (authoritativeReasoningMode === pendingTarget) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Clear the write barrier once refreshed authority matches the optimistic selection.
        setPendingTarget(null)
        setSelectedReasoningMode(authoritativeReasoningMode)
      }
      return
    }
    setSelectedReasoningMode(authoritativeReasoningMode)
  }, [authoritativeReasoningMode, pendingTarget])
  const handleChange = async (reasoningMode: LocalReasoningMode): Promise<void> => {
    const rollbackReasoningMode =
      pendingTarget ?? authoritativeReasoningMode
    setSelectedReasoningMode(reasoningMode)
    setPendingTarget(reasoningMode)
    setSaving(true)
    try {
      const persisted = await onChange(reasoningMode)
      if (!persisted) {
        setPendingTarget(null)
        setSelectedReasoningMode(rollbackReasoningMode)
      }
    } catch {
      setPendingTarget(null)
      setSelectedReasoningMode(rollbackReasoningMode)
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="space-y-2" aria-label={`${agent.display_name} reasoning`}>
      <label htmlFor={`cortex-${agent.key}-reasoning`} className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">
        Reasoning
      </label>
      <select
        id={`cortex-${agent.key}-reasoning`}
        value={selectedReasoningMode}
        disabled={disabled || saving}
        onChange={(event) => {
          void handleChange(event.target.value as LocalReasoningMode)
        }}
        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option === 'none' ? 'None' : 'High'}
          </option>
        ))}
      </select>
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Applies to the next response. Hidden reasoning is not shown in Cortex.
      </p>
    </section>
  )
}

function formatNumber(value: number | null | undefined): string { return value == null ? '—' : value.toLocaleString() }
function formatMilliseconds(value: number | null | undefined): string { return value == null ? '—' : `${Math.round(value)} ms` }
function formatCurrency(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: value < 0.01 ? 5 : 2 }).format(value)
}

function TraceList({ trace }: { trace: ToolTraceItem[] }): ReactElement | null {
  if (trace.length === 0) return null
  return <section className="rounded-xl border border-white/10 bg-black/20 p-3" aria-label="Tool trace"><p className="mb-2 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Tool trace</p><ul className="space-y-1.5">{trace.map((item, index) => <li key={`${item.name}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-zinc-300"><span className={item.status.toLowerCase() === 'ok' ? 'text-emerald-300' : 'text-red-300'}>{item.status}</span><span>{item.name}</span>{item.origin ? <span className="text-zinc-500">{item.origin}</span> : null}{item.billable_units ? <span className="text-amber-200">{item.billable_units} billable</span> : null}<span className="ml-auto text-zinc-500">{formatMilliseconds(item.duration_ms)}</span></li>)}</ul></section>
}

function MapsGroundingSources({ citations }: { citations: AgentQueryMetadata['citations'] }): ReactElement | null {
  const sources = citations.filter((citation) => citation.source === 'google_maps' && citation.uri)
  const uniqueSources = sources.filter((citation, index) => sources.findIndex((candidate) => candidate.uri === citation.uri) === index)
  if (uniqueSources.length === 0) return null
  return <section className="mt-3 space-y-1.5 border-t border-white/10 pt-3" aria-label="Google Maps sources"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Google Maps sources</p><ul className="space-y-1.5">{uniqueSources.map((citation) => <li key={citation.uri}><a className="flex rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-xs text-[#7EB3FF] hover:text-white" href={citation.uri ?? undefined} target="_blank" rel="noreferrer"><span><span translate="no">Google Maps</span>{citation.title ? `: ${citation.title}` : ''}</span><ExternalLink className="ml-auto mt-0.5 size-3 shrink-0" aria-hidden /></a></li>)}</ul></section>
}

function GoogleSearchSuggestions({ grounding }: { grounding: AgentQueryMetadata['grounding'] }): ReactElement | null {
  const content = grounding?.searchSuggestionsHtml
  if (!content) return null
  return <section className="mt-3 border-t border-white/10 pt-3" aria-label="Google Search suggestions"><p className="mb-1.5 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Google Search suggestions</p><iframe title="Google Search suggestions" srcDoc={content} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" className="h-20 w-full rounded-md border-0 bg-transparent" /></section>
}

export function ResponseMetrics({ metadata }: { metadata: AgentQueryMetadata | undefined }): ReactElement | null {
  if (!metadata) return null
  const { agent, usage, timing, cost, citations, toolSelection } = metadata
  const supplementaryCitations = citations.filter((citation) => citation.source !== 'google_maps')
  return <details className="mt-3 rounded-lg border border-white/10 bg-black/10">
    <summary className="cursor-pointer select-none px-3 py-2 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500 outline-none marker:text-[#C084FC] hover:text-zinc-300 focus-visible:ring-2 focus-visible:ring-[#7EB3FF]">Response information</summary>
    <div className="space-y-3 border-t border-white/10 p-3">
      {agent ? <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-zinc-500"><span>{providerDisplayName(agent.provider)} / {agent.key}</span><span>{agent.resolvedModel ?? agent.configuredModel ?? 'model unavailable'}</span>{agent.resolvedEffort ? <span>{agent.resolvedEffort} effort</span> : null}{agent.version ? <span>v{agent.version}</span> : null}</div> : null}
      {usage || timing || cost ? <div className="grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3"><Metric label="Tokens" value={formatNumber(usage?.totalTokens)} detail={`in ${formatNumber(usage?.inputTokens)} · out ${formatNumber(usage?.outputTokens)} · reasoning ${formatNumber(usage?.reasoningTokens)}`} /><Metric label="Latency" value={formatMilliseconds(timing?.totalMs)} detail={`provider ${formatMilliseconds(timing?.providerMs)} · tools ${formatMilliseconds(timing?.apexToolMs)}`} /><Metric label="Estimate" value={formatCurrency(cost?.totalCost, cost?.currency)} detail={`tokens ${formatCurrency(cost?.tokenCost, cost?.currency)} · hosted ${formatCurrency(cost?.hostedToolCost, cost?.currency)}`} /></div> : null}
      {cost?.pricingVersion || cost?.completeness ? <p className="font-mono text-[10px] text-zinc-600">{cost.pricingVersion ?? 'pricing unavailable'} · {cost.completeness ?? 'estimate unavailable'}</p> : null}
      {toolSelection ? <section className="rounded-lg border border-purple-300/15 bg-purple-950/10 p-2.5" aria-label="Resolved tool selection"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Resolved tools</p><p className="mt-1 font-mono text-[10px] text-zinc-400">{toolSelection.active_profile_name ?? 'Custom'} · {toolSelection.offered_tool_names.length} offered · ~{toolSelection.selected_schema_tokens.toLocaleString()} schema tokens</p>{toolSelection.rejected_tools.length > 0 ? <ul className="mt-1 space-y-1 text-[10px] text-red-200">{toolSelection.rejected_tools.map((failure) => <li key={`${failure.name}-${failure.code}`}>{failure.name}: {failure.reason}</li>)}</ul> : null}</section> : null}
      {supplementaryCitations.length > 0 ? <section className="space-y-1.5" aria-label="Citations"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Citations</p><ul className="space-y-1.5">{supplementaryCitations.map((citation, index) => <li key={`${citation.uri ?? citation.title ?? 'citation'}-${index}`} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-xs text-zinc-300">{citation.uri ? <a className="inline-flex items-center gap-1 text-[#7EB3FF] hover:text-white" href={citation.uri} target="_blank" rel="noreferrer"><span>{citation.title ?? citation.uri}</span><ExternalLink className="size-3" aria-hidden /></a> : <span>{citation.title ?? citation.source ?? 'Grounding source'}</span>}{citation.snippet ? <p className="mt-1 text-zinc-500">{citation.snippet}</p> : null}</li>)}</ul></section> : null}
    </div>
  </details>
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }): ReactElement {
  return <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5"><p className="font-mono uppercase tracking-wider text-zinc-500">{label}</p><p className="mt-1 font-mono text-zinc-200">{value}</p><p className="mt-1 text-zinc-500">{detail}</p></div>
}

function ContextUsed({ references, onOpenRecord }: { references: ReturnType<typeof parseAgentQueryResponse>['context_references'] | undefined; onOpenRecord: (recordId: string) => void }): ReactElement | null {
  if (!references || references.length === 0) return null
  return <details className="mt-3 rounded-lg border border-white/10 bg-black/10"><summary className="cursor-pointer select-none px-3 py-2 font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500 hover:text-zinc-300">Context used</summary><ul className="space-y-1.5 border-t border-white/10 p-3">{references.map((reference) => <li key={`${reference.namespace}-${reference.source_id}`} className="flex flex-wrap items-center gap-2 font-mono text-[10px] text-zinc-400"><span>{reference.namespace}</span><span className="text-zinc-600">{reference.status ?? 'reference'}</span>{reference.namespace === 'personal_context' ? <button type="button" onClick={() => onOpenRecord(reference.source_id)} className="text-[#9AC2FF] hover:text-white">Open record</button> : <span className="break-all text-zinc-600">{reference.locator}</span>}</li>)}</ul></details>
}

export function AssistantResponseDisplay({
  text,
  rawMetadata,
  onOpenRecord,
}: {
  text: string
  rawMetadata: Record<string, unknown>
  onOpenRecord: (recordId: string) => void
}): ReactElement {
  const response = parseAgentQueryResponse({ ...rawMetadata, answer: text })
  const metadata = response.metadata
  return <>
    {metadata?.agent ? <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{metadata.agent.key}</p> : null}
    <div className="text-sm leading-relaxed text-zinc-200"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" translate={typeof children === 'string' && children.startsWith('Google Maps:') ? 'no' : undefined} className="text-[#7EB3FF] hover:underline">{children}</a>,
      code: ({ className, children, ...props }) => className ? <code className={`${className} block font-mono text-xs text-zinc-200`} {...props}>{children}</code> : <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-purple-200" {...props}>{children}</code>,
      pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs text-zinc-200">{children}</pre>,
      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
      ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
      ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
      li: ({ children }) => <li className="leading-relaxed">{children}</li>,
      h1: ({ children }) => <h1 className="mb-2 font-orbitron text-base font-semibold text-white">{children}</h1>,
      h2: ({ children }) => <h2 className="mb-2 font-orbitron text-sm font-semibold text-white">{children}</h2>,
      h3: ({ children }) => <h3 className="mb-1 text-sm font-medium text-zinc-100">{children}</h3>,
      blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-[#C084FC] py-1 pl-3 italic text-zinc-400">{children}</blockquote>,
      table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse border border-white/10 text-xs text-zinc-200">{children}</table></div>,
      thead: ({ children }) => <thead className="bg-white/5 font-mono uppercase text-zinc-400">{children}</thead>,
      th: ({ children }) => <th className="border border-white/10 px-3 py-1.5 text-left font-semibold">{children}</th>,
      td: ({ children }) => <td className="border border-white/10 px-3 py-1.5">{children}</td>,
    }}>{text}</ReactMarkdown></div>
    {metadata ? <ResponseMetrics metadata={metadata} /> : null}
    <ContextUsed references={response.context_references} onOpenRecord={onOpenRecord} />
    <MapsGroundingSources citations={metadata?.citations ?? []} />
    <GoogleSearchSuggestions grounding={metadata?.grounding ?? null} />
    <TraceList trace={response.tool_trace ?? []} />
    {response.tool_outputs && response.tool_outputs.length > 0 ? <CortexToolCards toolOutputs={response.tool_outputs} /> : null}
  </>
}

function useCompactCortexLayout(): boolean {
  const [compact, setCompact] = useState(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(max-width: 1279px), (max-height: 820px)').matches
      : false
  ))
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(max-width: 1279px), (max-height: 820px)')
    const update = (): void => setCompact(query.matches)
    update()
    query.addEventListener?.('change', update)
    return () => query.removeEventListener?.('change', update)
  }, [])
  return compact
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

function LocalModelLifecycle({ agent, busy, actionPending, onLoad, onUnload }: { agent: AgentStatus; busy: boolean; actionPending: boolean; onLoad: () => Promise<boolean>; onUnload: () => Promise<boolean> }): ReactElement {
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
    const successful = canUnload ? await onUnload() : await onLoad()
    if (!successful) setError(`${canUnload ? 'Unload' : 'Load'} failed. Check Ollama status and try again.`)
  }
  if (lifecycleState === 'Loaded') {
    return <section className="space-y-2" aria-label="Local model lifecycle">
      <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Local model</p>
      <div className="rounded-lg border border-orange-500/25 bg-orange-950/10 p-3">
        <div className="flex items-center justify-between gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${stateClassName}`} aria-live="polite"><span className="size-1.5 rounded-full bg-current" aria-hidden />{lifecycleState}</span><span className="font-mono text-[10px] text-zinc-500">{agent.loaded_model?.name ?? agent.configured_model}</span></div>
        <button type="button" disabled={disabled} onClick={() => void action()} className="mt-3 inline-flex w-full items-center justify-center rounded-md border border-orange-400/40 bg-orange-950/25 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-orange-100 transition-colors hover:border-orange-300 hover:bg-orange-950/45 disabled:cursor-not-allowed disabled:opacity-45">{transition ? <Loader2 className="cortex-lifecycle-spinner mr-1.5 size-3.5" aria-hidden /> : null}{transition ? 'Unloading…' : actionLabel}</button>
        <p className="mt-2 font-mono text-[10px] text-orange-100/75" aria-live="polite">{busy ? 'In use · auto-unload paused' : `Auto-unload in ${formatCountdown(idleUnloadRemaining)}`}</p>
        <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">Loading pre-warms this agent; normal requests can still load it when needed. Unloading frees memory without changing the selected agent.</p>
        {busy ? <p className="mt-1 text-[10px] text-amber-200">Lifecycle actions are unavailable while local inference is active.</p> : null}
        {error ? <p className="mt-1 text-[10px] text-red-200" role="alert">{error}</p> : null}
      </div>
    </section>
  }
  return <section className="space-y-2" aria-label="Local model lifecycle"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Local model</p><div className="rounded-lg border border-orange-500/25 bg-orange-950/10 p-3"><div className="flex items-center justify-between gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${stateClassName}`} aria-live="polite"><span className={`size-1.5 rounded-full bg-current ${transition ? 'cortex-lifecycle-status--transitioning' : ''}`} aria-hidden />{lifecycleState}</span><span className="font-mono text-[10px] text-zinc-500">{agent.configured_model}</span></div><button type="button" disabled={disabled} onClick={() => void action()} className="mt-3 inline-flex w-full items-center justify-center rounded-md border border-orange-400/40 bg-orange-950/25 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-orange-100 transition-colors hover:border-orange-300 hover:bg-orange-950/45 disabled:cursor-not-allowed disabled:opacity-45">{transition ? <Loader2 className="cortex-lifecycle-spinner mr-1.5 size-3.5" aria-hidden /> : null}{transition ? (canUnload ? 'Unloading…' : 'Loading…') : actionLabel}</button><p className="mt-2 text-[11px] leading-relaxed text-zinc-500">Loading pre-warms this agent; normal requests can still load it when needed. Unloading frees memory without changing the selected agent.</p>{!agent.active && lifecycleState === 'Unloaded' ? <p className="mt-1 text-[10px] text-zinc-600">Loading this agent may replace another resident local model.</p> : null}{busy ? <p className="mt-1 text-[10px] text-amber-200">Lifecycle actions are unavailable while local inference is active.</p> : null}{agent.reason && lifecycleState === 'Unavailable' ? <p className="mt-1 text-[10px] text-red-200">{agent.reason}</p> : null}{error ? <p className="mt-1 text-[10px] text-red-200" role="alert">{error}</p> : null}</div></section>
}

export function CortexWorkspace(props: CortexWorkspaceProps): ReactElement {
  const [compactPanel, setCompactPanel] = useState<'conversations' | 'inspector' | null>(null)
  const [inspectorTab, setInspectorTab] = useState<typeof INSPECTOR_TABS[number]>('controls')
  const runsState = useCortexRuns({ pollingEnabled: true })
  const activeRun = runsState.activeRuns[0] ?? null
  const selectInspectorTab = useCallback((tab: typeof INSPECTOR_TABS[number]) => setInspectorTab(tab), [])
  const onInspectorTabKeyDown = useCallback((event: KeyboardEvent<HTMLButtonElement>) => {
    const index = INSPECTOR_TABS.indexOf(inspectorTab)
    const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? INSPECTOR_TABS.length - 1 : offset ? (index + offset + INSPECTOR_TABS.length) % INSPECTOR_TABS.length : null
    if (next === null) return
    event.preventDefault()
    const tab = INSPECTOR_TABS[next]
    setInspectorTab(tab)
    document.getElementById(`cortex-inspector-tab-${tab}`)?.focus()
  }, [inspectorTab])
  const actionEffectRef = useRef<string | null>(null)
  const onContextActionProposed = useCallback((action: { action_id: string }) => {
    props.actions.setSelectedActionId(action.action_id)
    setInspectorTab('actions')
  }, [props.actions])
  const contextInspector = useContextInspector(true, onContextActionProposed)
  const selectContextRecord = contextInspector.selectRecord
  const rememberVerifiedRecord = contextInspector.rememberVerifiedRecord
  const openContextRecord = useCallback((recordId: string) => {
    setInspectorTab('context')
    void selectContextRecord(recordId)
  }, [selectContextRecord])
  useEffect(() => {
    const action = props.actions.detail
    if (!action || action.status !== 'verified' || actionEffectRef.current === action.action_id) return
    if (!['remember_personal_context', 'reconcile_personal_context'].includes(action.proposal.capability_name)) return
    const evidence = [...action.events].reverse().find((event) => event.to_status === 'verified')?.evidence
    const recordId = evidence?.outcome === 'created' && typeof evidence.record_id === 'string'
      ? evidence.record_id
      : evidence?.outcome === 'corrected' && typeof evidence.target_id === 'string'
        ? evidence.target_id : null
    actionEffectRef.current = action.action_id
    rememberVerifiedRecord(recordId)
  }, [rememberVerifiedRecord, props.actions.detail])
  const compactLayout = useCompactCortexLayout()
  const isQuerying = props.isQuerying
  const interactionDisabled = isQuerying || Boolean(props.submissionPending) || Boolean(props.conversationHydrating)
  const activeStatus = props.agentsStatus.find((agent) => agent.key === props.activeAgent)
  const localContextLocked =
    props.lifecycleBusy ||
    props.lifecycleActionPending ||
    isQuerying ||
    Boolean(props.conversationHydrating) ||
    Boolean(activeStatus?.active || activeStatus?.loading)
  const gridClassName = compactLayout
    ? 'grid min-h-0 flex-1 grid-cols-1'
    : 'grid min-h-0 flex-1 grid-cols-[14rem_minmax(0,1fr)_22rem]'
  const assistantComposer: ApexAssistantComposerProps = {
    activeAgent: props.activeAgent,
    activeAgentName: activeStatus?.display_name ?? props.activeAgent,
    error: props.error,
    tools: {
      catalog: props.toolCatalog ?? null,
      selectedToolNames: props.selectedToolNames ?? [],
      activeToolProfileId: props.activeToolProfileId ?? null,
      onSelectionChange: props.onToolSelectionChange ?? (() => undefined),
      onProfileChange: props.onToolProfileChange ?? (() => undefined),
      preflight: props.toolPreflight,
      preflightLoading: props.toolPreflightLoading,
      catalogError: props.toolCatalogError,
      preflightError: props.toolPreflightError,
      profileFeedback: props.toolProfileFeedback,
      profileError: props.toolProfileError,
      disabled: interactionDisabled || !props.selectionReady,
      onSaveProfile: props.onSaveToolProfile,
      onDuplicateProfile: props.onDuplicateToolProfile,
      onRenameProfile: props.onRenameToolProfile,
      onDeleteProfile: props.onDeleteToolProfile,
      onRestoreProfile: props.onRestoreToolProfile,
      onSetDefaultProfile: props.onSetDefaultToolProfile,
    },
  }
  return <section className={`relative z-[var(--z-bento-hud)] mx-auto flex min-h-0 w-full flex-1 flex-col ${compactLayout ? 'overflow-visible' : 'overflow-hidden'} rounded-2xl border border-white/10 bg-zinc-950/45 shadow-2xl backdrop-blur-xl`} aria-label="Cortex workspace">
    <header className="flex flex-wrap items-center gap-3 border-b border-white/10 bg-black/20 px-4 py-3 sm:px-5"><div className="mr-auto flex items-center gap-2"><span className="hud-icon-badge size-8 text-[#C084FC]"><BrainCircuit className="size-4" aria-hidden /></span><div><h1 className="font-orbitron text-sm font-semibold uppercase tracking-[0.16em] text-white">Cortex</h1><p className="font-mono text-[10px] text-zinc-500">Operate and configure the Apex Agent</p></div></div></header>
    <div className={`${compactLayout ? 'flex' : 'hidden'} shrink-0 gap-2 border-b border-white/10 bg-black/20 p-2`}><button type="button" disabled={interactionDisabled} aria-expanded={compactPanel === 'conversations'} aria-controls="cortex-conversations-compact" onClick={() => setCompactPanel((panel) => panel === 'conversations' ? null : 'conversations')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 disabled:opacity-40">Conversations</button><button type="button" disabled={interactionDisabled} aria-expanded={compactPanel === 'inspector'} aria-controls="cortex-inspector-compact" onClick={() => setCompactPanel((panel) => panel === 'inspector' ? null : 'inspector')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 disabled:opacity-40">Inspector</button></div>
    {compactPanel === 'conversations' ? <div id="cortex-conversations-compact" className={compactLayout ? '' : 'xl:hidden'}><ApexConversationRail disabled={interactionDisabled} className="block w-full border-b border-r-0" /></div> : null}
    <div className={gridClassName}><ApexConversationRail disabled={interactionDisabled} className={compactLayout ? 'hidden' : 'hidden xl:block'} /><div className="order-1 flex min-h-0 flex-col">
        <CortexActiveRunStrip
          run={activeRun}
          onInspect={() => {
            setInspectorTab('activity')
            if (compactLayout) setCompactPanel('inspector')
          }}
          onCancel={runsState.cancelRun}
          className="mx-4 mt-3 mb-1"
        />
        {props.agentQueriesEnabled ? <ApexAssistantThread renderAgent={(text, metadata) => <AssistantResponseDisplay text={text} rawMetadata={metadata} onOpenRecord={openContextRecord} />} composer={assistantComposer} disabled={interactionDisabled || !props.selectionReady} logoProps={props.logoProps} /> : <footer className="border-t border-white/10 p-4 text-sm text-zinc-500">Agent queries are disabled in Settings.</footer>}</div>
      <aside id="cortex-inspector-compact" className={`order-2 space-y-4 border-t border-white/10 bg-black/15 p-4 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:border-t-0 scrollbar-thin ${compactPanel !== 'inspector' ? (compactLayout ? 'hidden' : 'hidden xl:block') : ''}`} aria-label="Cortex inspector"><div role="tablist" aria-label="Cortex inspector sections" className="flex border-b border-white/10">{INSPECTOR_TABS.map((tab) => <button key={tab} id={`cortex-inspector-tab-${tab}`} type="button" role="tab" tabIndex={inspectorTab === tab ? 0 : -1} aria-selected={inspectorTab === tab} aria-controls={`cortex-inspector-${tab}`} onKeyDown={onInspectorTabKeyDown} onClick={() => selectInspectorTab(tab)} className={`px-2 py-2 font-mono text-[10px] uppercase tracking-wide outline-none focus-visible:ring-1 focus-visible:ring-[#7EB3FF] ${inspectorTab === tab ? 'text-[#9AC2FF]' : 'text-zinc-500 hover:text-zinc-200'}`}>{tab}</button>)}</div>{inspectorTab === 'controls' ? <div id="cortex-inspector-controls" role="tabpanel" aria-labelledby="cortex-inspector-tab-controls" className="space-y-4"><section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Apex Agent</p><p className="text-[11px] text-zinc-500">Select a model to choose cloud or local execution.</p></section><RuntimeControls {...props} activeStatus={activeStatus ?? null} localContextLocked={localContextLocked} /><ContextControl {...props} /></div> : null}{inspectorTab === 'context' ? <div id="cortex-inspector-context" role="tabpanel" aria-labelledby="cortex-inspector-tab-context"><CortexContext inspector={contextInspector} demoModeActive={props.demoModeActive} /></div> : null}{inspectorTab === 'actions' ? <div id="cortex-inspector-actions" role="tabpanel" aria-labelledby="cortex-inspector-tab-actions"><CortexActions actions={props.actions} demoModeActive={props.demoModeActive} /></div> : null}{inspectorTab === 'activity' ? <div id="cortex-inspector-activity" role="tabpanel" aria-labelledby="cortex-inspector-tab-activity"><CortexActivity runsState={runsState} agentsStatus={props.agentsStatus} diagnostics={props.diagnostics} /></div> : null}
      </aside>
    </div>
  </section>
}

function RuntimeControls({
  activeStatus,
  localContextLocked,
  ...props
}: CortexWorkspaceProps & {
  activeStatus: AgentStatus | null
  localContextLocked: boolean
}): ReactElement {
  const controlsDisabled = props.isQuerying || Boolean(props.submissionPending) || Boolean(props.conversationHydrating)
  const selectedModel = props.selectedModel ?? activeStatus?.configured_model ?? ''
  const hostedTools = props.hostedTools ?? { google_search: false, google_maps: false }
  const catalog = resolveModelCatalog(activeStatus ?? undefined)
  const selectedModelEntry = catalog.find((entry) => entry.model_id === selectedModel)
  const selectedRuntimeStatus = activeStatus && selectedModelEntry
    ? {
        ...activeStatus,
        configured_model: selectedModelEntry.model_id,
        provider: selectedModelEntry.provider,
        runtime: selectedModelEntry.runtime,
        model_stability: selectedModelEntry.stability,
        reasoning_options: selectedModelEntry.reasoning_options ?? null,
        default_reasoning: selectedModelEntry.default_reasoning ?? null,
        context_window: selectedModelEntry.runtime === 'local'
          ? props.localContextWindow
          : selectedModelEntry.default_context_window ?? null,
        context_window_options: selectedModelEntry.context_options ?? null,
        context_window_high_resource_options: selectedModelEntry.high_resource_context_options ?? null,
        default_context_window: selectedModelEntry.default_context_window ?? null,
        reasoning_mode: selectedModelEntry.runtime === 'local'
          ? props.localReasoningMode
          : selectedModelEntry.default_reasoning_mode ?? null,
        reasoning_mode_options: selectedModelEntry.reasoning_modes ?? null,
        default_reasoning_mode: selectedModelEntry.default_reasoning_mode ?? null,
        status: selectedModelEntry.status ?? activeStatus.status,
        status_source: selectedModelEntry.status_source ?? activeStatus.status_source,
        status_checked_at: selectedModelEntry.status_checked_at ?? activeStatus.status_checked_at,
        active: selectedModelEntry.active ?? false,
        loading: selectedModelEntry.loading ?? false,
        reason: selectedModelEntry.reason ?? null,
        loaded_model: selectedModelEntry.loaded_model ?? null,
      }
    : activeStatus
  const hostedCapabilities = hostedCapabilitiesForModel(selectedModel, catalog)
  const reasoningOptions = selectedModelEntry?.reasoning_options ?? []
  const isLocal = selectedModelEntry?.runtime === 'local'

  return (
    <div className="space-y-4">
      <ModelSelector
        selectedModelId={selectedModel}
        onModelChange={props.onModelChange ?? (() => {})}
        catalog={catalog}
        disabled={controlsDisabled}
        isQuerying={props.isQuerying}
        verifyingModelId={props.verifyingCloudModel}
        onVerify={props.onVerifyCloudAgent}
      />
      {!isLocal && reasoningOptions.length > 0 ? <section className="space-y-2"><label htmlFor="cortex-effort" className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Reasoning effort</label><select id="cortex-effort" value={props.cloudEffort} disabled={controlsDisabled} onChange={(event) => props.onEffortChange(event.target.value as CloudEffort)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF]">{reasoningOptions.map((effort) => <option key={effort} value={effort}>{formatReasoningLabel(effort)}</option>)}</select></section> : null}
      {isLocal && selectedRuntimeStatus ? <><LocalReasoningControl agent={selectedRuntimeStatus} disabled={controlsDisabled} onChange={props.onLocalReasoningModeChange} /><LocalContextControl agent={selectedRuntimeStatus} disabled={localContextLocked} onChange={props.onLocalContextWindowChange} /><LocalModelLifecycle agent={selectedRuntimeStatus} busy={props.lifecycleBusy || controlsDisabled} actionPending={props.lifecycleActionPending} onLoad={() => props.onLoadLocalModel(selectedModel)} onUnload={props.onUnloadLocalModel} /></> : null}

      {hostedCapabilities.length > 0 ? (
        <GroundingControls note="Apex Brave Search remains the standard search capability when connected.">
          {hostedCapabilities.includes('google_search') ? (
            <GroundingToggle
              label="Google Search"
              detail="Provider grounding for later requests"
              checked={hostedTools.google_search}
              disabled={controlsDisabled}
              onChange={(enabled) => props.onHostedToolChange('google_search', enabled)}
            />
          ) : null}
          {hostedCapabilities.includes('google_maps') ? (
            <GroundingToggle
              label="Google Maps"
              detail="Provider grounding for later requests"
              checked={hostedTools.google_maps}
              disabled={controlsDisabled}
              onChange={(enabled) => props.onHostedToolChange('google_maps', enabled)}
            />
          ) : null}
        </GroundingControls>
      ) : null}

      {props.devModeActive ? (
        <section className="space-y-2" aria-label="Sandbox mode">
          <label className="flex items-center justify-between gap-3 rounded-lg border border-cyan-300/20 bg-cyan-950/10 px-3 py-2">
            <span>
              <span className="block font-mono text-[10px] uppercase tracking-wider text-cyan-100">Sandbox mode</span>
              <span className="block text-[11px] text-zinc-500">Isolated history and masked context for DEV_MODE queries.</span>
            </span>
            <input
              aria-label="Sandbox mode"
              type="checkbox"
              disabled={controlsDisabled}
              checked={props.sandboxMode}
              onChange={(event) => props.onSandboxModeChange(event.target.checked)}
              className="size-4 accent-cyan-400"
            />
          </label>
        </section>
      ) : null}
    </div>
  )
}

function ContextControl(props: CortexWorkspaceProps): ReactElement {
  const selectedNames = props.selectedToolNames ?? []
  const activeProfile = props.toolCatalog?.profiles.find(
    (profile) => profile.id === props.activeToolProfileId,
  )
  const unavailableCount = selectedNames.filter((name) => {
    const tool = props.toolCatalog?.tools.find((item) => item.name === name)
    return !tool || !tool.available || !tool.allowed_for_agent
  }).length
  return <div className="space-y-4"><section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Context</p><label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span className="text-xs text-zinc-300">Current HUD snapshot</span><input type="checkbox" checked={props.snapshotAttached} disabled={!props.snapshotAvailable || props.isQuerying || Boolean(props.submissionPending) || Boolean(props.conversationHydrating)} onChange={(event) => props.onSnapshotAttachedChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label><p className="text-[11px] leading-relaxed text-zinc-500">{props.snapshotAttached && props.snapshotAvailable ? 'The current snapshot will be included with the next turn.' : 'No HUD context will be attached.'}</p><label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span><span className="block text-xs text-zinc-300">Personal context</span><span className="block text-[11px] text-zinc-500">Include bounded saved context and older conversations.</span></span><input aria-label="Personal context" type="checkbox" checked={props.personalContextEnabled ?? false} disabled={props.isQuerying || Boolean(props.submissionPending) || Boolean(props.conversationHydrating)} onChange={(event) => { void props.onPersonalContextEnabledChange?.(event.target.checked) }} className="size-4 accent-[#0F4DB8]" /></label></section><section className="space-y-2" aria-label="Selected tools summary"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Prompt tools</p><div className="rounded-lg border border-purple-300/15 bg-purple-950/10 p-3 font-mono text-[10px] text-zinc-400"><p className="text-zinc-200">{activeProfile?.name ?? 'Custom'} · {selectedNames.length} selected</p><p className="mt-1 text-zinc-500">{props.selectionReady ? 'Configured beside the prompt.' : 'Hydrating this Agent selection…'}</p>{props.toolCatalog?.provider_hosted_tools.length ? <p className="mt-1 text-cyan-200/80">Hosted grounding: {props.toolCatalog.provider_hosted_tools.join(', ')}</p> : <p className="mt-1 text-zinc-600">Hosted grounding is controlled separately.</p>}{unavailableCount > 0 ? <p className="mt-1 text-red-200">{unavailableCount} unavailable selection{unavailableCount === 1 ? '' : 's'} need removal.</p> : null}{props.contextUsage ? <p className="mt-2 text-zinc-600">Last local estimate: {formatNumber(props.contextUsage.estimated_prompt_tokens)}/{formatNumber(props.contextUsage.context_window)} tokens.</p> : null}{props.toolCatalogError ? <p className="mt-2 text-red-200" role="alert">{props.toolCatalogError}</p> : null}</div></section></div>
}
function GroundingToggle({ label, detail, checked, disabled = false, onChange }: { label: string; detail: string; checked: boolean; disabled?: boolean; onChange: (enabled: boolean) => void }): ReactElement { return <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50"><span><span className="block font-mono text-[10px] uppercase tracking-wider text-zinc-300">{label}</span><span className="block text-[11px] text-zinc-500">{detail} · {checked ? 'Enabled' : 'Disabled'}</span></span><input aria-label={`${label} grounding`} type="checkbox" disabled={disabled} checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label> }
function GroundingControls({ note, children }: { note: string; children: React.ReactNode }): ReactElement { return <section className="space-y-2" aria-label="Grounding"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Grounding</p>{children}<p className="text-[11px] leading-relaxed text-zinc-500">{note}</p></section> }
