import { ExternalLink, Loader2, Plus } from 'lucide-react'
import { useEffect, useRef, useState, type ReactElement } from 'react'

import { parseAgentQueryResponse, type AgentMessage, type AgentQueryMetadata, type ToolTraceItem } from '../hooks/useCortex'
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
  ToolOutputItem,
} from '../types/telemetry'
import type { PantheraHostedToolsSettings } from '../types/settings'
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
import { ApexLogo, type ApexLogoProps } from './ApexLogo'
import { AgentQueryBar } from './AgentQueryBar'
import { AgentSelector } from './AgentSelector'
import { ModelSelector } from './ModelSelector'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'
import { ApexAssistantNewConversation, ApexAssistantRuntime, ApexAssistantThread, ApexConversationRail, type ApexAssistantRunConfig } from './ApexAssistantRuntime'

interface CortexWorkspaceProps {
  activeAgent: AgentKey
  cloudEffort: CloudEffort
  pantheraModel: string
  felisModel?: string
  pantheraHostedTools: PantheraHostedToolsSettings
  devModeActive: boolean
  sandboxMode: boolean
  agentQueriesEnabled: boolean
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  history: AgentMessage[]
  latestTrace: ToolTraceItem[]
  error: string | null
  contextUsage: LocalContextUsage | null
  toolCatalog?: ToolCatalog | null
  selectedToolNames?: string[]
  activeToolProfileId?: string | null
  selectionReady?: boolean
  submissionPending?: boolean
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
  draftPrompt?: string
  onDraftChange?: (value: string) => void
  isQuerying: boolean
  logoProps: Omit<ApexLogoProps, 'className'>
  lifecycleBusy: boolean
  lifecycleActionPending: boolean
  verifyingCloudAgent: AgentKey | null
  onLoadLocalModel: () => Promise<boolean>
  onUnloadLocalModel: () => Promise<boolean>
  onVerifyCloudAgent: (agent: 'panthera') => Promise<boolean>
  snapshotAttached: boolean
  snapshotAvailable: boolean
  onSnapshotAttachedChange: (attached: boolean) => void
  onAgentChange: (agent: AgentKey) => void
  onPantheraModelChange: (model: string) => void
  onFelisModelChange?: (model: string) => void
  onEffortChange: (effort: CloudEffort) => void
  onHostedToolChange: (tool: HostedTool, enabled: boolean) => void
  onSandboxModeChange: (enabled: boolean) => void
  onLocalContextWindowChange: (contextWindow: number) => Promise<boolean>
  onLocalReasoningModeChange: (reasoningMode: LocalReasoningMode) => Promise<boolean>
  onSubmit: (
    query: string,
    agent: AgentKey,
    selectedToolNames: string[],
    toolProfileId: string | null,
  ) => Promise<boolean>
  onNewSession: () => void
  actions: UseActionsResult
  demoModeActive: boolean
  assistantRunConfig?: ApexAssistantRunConfig
  onAssistantPreflight?: (config: ApexAssistantRunConfig) => Promise<boolean>
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

function ResponseMetrics({ metadata }: { metadata: AgentQueryMetadata | undefined }): ReactElement | null {
  if (!metadata) return null
  const { agent, usage, timing, cost, citations, toolSelection } = metadata
  const supplementaryCitations = citations.filter((citation) => citation.source !== 'google_maps')
  return <div className="mt-3 space-y-3">
    {agent ? <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-white/10 pt-3 font-mono text-[10px] text-zinc-500"><span>{providerDisplayName(agent.provider)} / {agent.key}</span><span>{agent.resolvedModel ?? agent.configuredModel ?? 'model unavailable'}</span>{agent.resolvedEffort ? <span>{agent.resolvedEffort} effort</span> : null}{agent.version ? <span>v{agent.version}</span> : null}</div> : null}
    {usage || timing || cost ? <div className="grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3"><Metric label="Tokens" value={formatNumber(usage?.totalTokens)} detail={`in ${formatNumber(usage?.inputTokens)} · out ${formatNumber(usage?.outputTokens)} · reasoning ${formatNumber(usage?.reasoningTokens)}`} /><Metric label="Latency" value={formatMilliseconds(timing?.totalMs)} detail={`provider ${formatMilliseconds(timing?.providerMs)} · tools ${formatMilliseconds(timing?.apexToolMs)}`} /><Metric label="Estimate" value={formatCurrency(cost?.totalCost, cost?.currency)} detail={`tokens ${formatCurrency(cost?.tokenCost, cost?.currency)} · hosted ${formatCurrency(cost?.hostedToolCost, cost?.currency)}`} /></div> : null}
    {cost?.pricingVersion || cost?.completeness ? <p className="font-mono text-[10px] text-zinc-600">{cost.pricingVersion ?? 'pricing unavailable'} · {cost.completeness ?? 'estimate unavailable'}</p> : null}
    {toolSelection ? <section className="rounded-lg border border-purple-300/15 bg-purple-950/10 p-2.5" aria-label="Resolved tool selection"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Resolved tools</p><p className="mt-1 font-mono text-[10px] text-zinc-400">{toolSelection.active_profile_name ?? 'Custom'} · {toolSelection.offered_tool_names.length} offered · ~{toolSelection.selected_schema_tokens.toLocaleString()} schema tokens</p>{toolSelection.rejected_tools.length > 0 ? <ul className="mt-1 space-y-1 text-[10px] text-red-200">{toolSelection.rejected_tools.map((failure) => <li key={`${failure.name}-${failure.code}`}>{failure.name}: {failure.reason}</li>)}</ul> : null}</section> : null}
    {supplementaryCitations.length > 0 ? <section className="space-y-1.5" aria-label="Citations"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Citations</p><ul className="space-y-1.5">{supplementaryCitations.map((citation, index) => <li key={`${citation.uri ?? citation.title ?? 'citation'}-${index}`} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-xs text-zinc-300">{citation.uri ? <a className="inline-flex items-center gap-1 text-[#7EB3FF] hover:text-white" href={citation.uri} target="_blank" rel="noreferrer"><span>{citation.title ?? citation.uri}</span><ExternalLink className="size-3" aria-hidden /></a> : <span>{citation.title ?? citation.source ?? 'Grounding source'}</span>}{citation.snippet ? <p className="mt-1 text-zinc-500">{citation.snippet}</p> : null}</li>)}</ul></section> : null}
  </div>
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }): ReactElement {
  return <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5"><p className="font-mono uppercase tracking-wider text-zinc-500">{label}</p><p className="mt-1 font-mono text-zinc-200">{value}</p><p className="mt-1 text-zinc-500">{detail}</p></div>
}

function renderAssistantResponse(text: string, rawMetadata: Record<string, unknown>): ReactElement {
  const response = parseAgentQueryResponse({ ...rawMetadata, answer: text })
  const metadata = response.metadata
  return <>
    {metadata?.agent ? <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{metadata.agent.key}</p> : null}
    <div className="text-sm leading-relaxed text-zinc-200"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-[#7EB3FF] hover:underline">{children}</a>,
      code: ({ className, children, ...props }) => className ? <code className={`${className} block font-mono text-xs text-zinc-200`} {...props}>{children}</code> : <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-purple-200" {...props}>{children}</code>,
      pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs text-zinc-200">{children}</pre>,
      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
      ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
      ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
      h1: ({ children }) => <h1 className="mb-2 font-orbitron text-base font-semibold text-white">{children}</h1>,
      h2: ({ children }) => <h2 className="mb-2 font-orbitron text-sm font-semibold text-white">{children}</h2>,
      h3: ({ children }) => <h3 className="mb-1 text-sm font-medium text-zinc-100">{children}</h3>,
      blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-[#C084FC] py-1 pl-3 italic text-zinc-400">{children}</blockquote>,
    }}>{text}</ReactMarkdown></div>
    {metadata ? <ResponseMetrics metadata={metadata} /> : null}
    <MapsGroundingSources citations={metadata?.citations ?? []} />
    <GoogleSearchSuggestions grounding={metadata?.grounding ?? null} />
    <TraceList trace={response.tool_trace ?? []} />
    {response.tool_outputs && response.tool_outputs.length > 0 ? <CortexToolCards toolOutputs={response.tool_outputs} /> : null}
  </>
}

export function Conversation({ history, latestTrace, error, isQuerying, agentsStatus, activeAgent, onPromptSelect }: { history: AgentMessage[]; latestTrace: ToolTraceItem[]; error: string | null; isQuerying: boolean; agentsStatus: AgentStatus[]; activeAgent: AgentKey; onPromptSelect: ((query: string) => void) | null }): ReactElement {
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
      return <div key={`agent-${index}`} className="max-w-5xl"><div className="rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3"><p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{message.metadata?.agent?.key ?? agentName}</p><div className="text-sm leading-relaxed text-zinc-200"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" translate={typeof children === 'string' && children.startsWith('Google Maps:') ? 'no' : undefined} className="text-[#7EB3FF] hover:underline">{children}</a>, code: ({ className, children, ...props }) => className ? <code className={`${className} block font-mono text-xs text-zinc-200`} {...props}>{children}</code> : <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-purple-200" {...props}>{children}</code>, pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs text-zinc-200">{children}</pre>, p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>, ul: ({ children }) => <ul className="mb-2 list-disc pl-5 space-y-1">{children}</ul>, ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 space-y-1">{children}</ol>, li: ({ children }) => <li className="leading-relaxed">{children}</li>, h1: ({ children }) => <h1 className="mb-2 font-orbitron text-base font-semibold text-white">{children}</h1>, h2: ({ children }) => <h2 className="mb-2 font-orbitron text-sm font-semibold text-white">{children}</h2>, h3: ({ children }) => <h3 className="mb-1 text-sm font-medium text-zinc-100">{children}</h3>, blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-[#C084FC] pl-3 py-1 italic text-zinc-400">{children}</blockquote>, table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse border border-white/10 text-xs text-zinc-200">{children}</table></div>, thead: ({ children }) => <thead className="bg-white/5 font-mono uppercase text-zinc-400">{children}</thead>, th: ({ children }) => <th className="border border-white/10 px-3 py-1.5 text-left font-semibold">{children}</th>, td: ({ children }) => <td className="border border-white/10 px-3 py-1.5">{children}</td> }}>{message.content}</ReactMarkdown></div><MapsGroundingSources citations={message.metadata?.citations ?? []} /><GoogleSearchSuggestions grounding={message.metadata?.grounding ?? null} /><TraceList trace={message.tool_trace ?? (index === history.length - 1 ? latestTrace : [])} /><ResponseMetrics metadata={message.metadata} /></div>{toolOutputs.length > 0 ? <CortexToolCards toolOutputs={toolOutputs} /> : null}</div>
    })}
    {error ? <p className="rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-2 text-sm text-red-200" role="alert">{error}</p> : null}
    {isQuerying ? <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-[#D8B4FE]"><Loader2 className="size-4 animate-spin" aria-hidden />{agentName} working</div> : null}
    <div ref={endRef} />
  </div>
}

function AssistantBoundary({ config, beforeRun, onRunningChange, children }: { config?: ApexAssistantRunConfig; beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>; onRunningChange: (running: boolean) => void; children: React.ReactNode }): ReactElement {
  if (!config) return <>{children}</>
  return <ApexAssistantRuntime config={config} beforeRun={beforeRun} onRunningChange={(running) => onRunningChange(running)}>{children}</ApexAssistantRuntime>
}

function useCompactCortexLayout(): boolean {
  const [compact, setCompact] = useState(false)
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
        <div className="flex items-center justify-between gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${stateClassName}`} aria-live="polite"><span className="size-1.5 rounded-full bg-current" aria-hidden />{lifecycleState}</span><span className="font-mono text-[10px] text-zinc-500">{agent.configured_model}</span></div>
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
  const [assistantRunning, setAssistantRunning] = useState(false)
  const [compactPanel, setCompactPanel] = useState<'conversations' | 'inspector' | null>(null)
  const compactLayout = useCompactCortexLayout()
  const isQuerying = props.isQuerying || assistantRunning
  const activeStatus = props.agentsStatus.find((agent) => agent.key === props.activeAgent)
  const localContextLocked =
    props.lifecycleBusy ||
    props.lifecycleActionPending ||
    isQuerying ||
    Boolean(activeStatus?.active || activeStatus?.loading)
  const promptChipsEnabled =
    props.agentQueriesEnabled &&
    (props.selectionReady ?? false) &&
    !props.submissionPending &&
    props.toolPreflight?.can_proceed !== false
  return <AssistantBoundary config={props.assistantRunConfig} beforeRun={props.onAssistantPreflight} onRunningChange={setAssistantRunning}><section className="relative z-[var(--z-bento-hud)] mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-zinc-950/45 shadow-2xl backdrop-blur-xl" aria-label="Cortex workspace">
    <header className="flex flex-wrap items-center gap-3 border-b border-white/10 bg-black/20 px-4 py-3 sm:px-5"><div className="mr-auto flex items-center gap-2"><div data-slot="cortex-logo" className="filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)]"><ApexLogo {...props.logoProps} className="h-8 w-auto" /></div><div><h1 className="font-orbitron text-sm font-semibold uppercase tracking-[0.16em] text-white">Cortex</h1><p className="font-mono text-[10px] text-zinc-500">Operate and configure Apex Agents</p></div></div>{props.assistantRunConfig ? <ApexAssistantNewConversation disabled={isQuerying || Boolean(props.submissionPending)} /> : <button type="button" onClick={props.onNewSession} disabled={props.isQuerying || props.submissionPending} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:text-white disabled:opacity-40"><Plus className="size-3.5" aria-hidden />New session</button>}</header>
    {props.assistantRunConfig ? <div className={`${compactLayout ? 'flex' : 'hidden xl:flex'} shrink-0 gap-2 border-b border-white/10 bg-black/20 p-2`}><button type="button" aria-expanded={compactPanel === 'conversations'} aria-controls="cortex-conversations-compact" onClick={() => setCompactPanel((panel) => panel === 'conversations' ? null : 'conversations')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300">Conversations</button><button type="button" aria-expanded={compactPanel === 'inspector'} aria-controls="cortex-inspector-compact" onClick={() => setCompactPanel((panel) => panel === 'inspector' ? null : 'inspector')} className="rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300">Inspector</button></div> : null}
    {props.assistantRunConfig && compactPanel === 'conversations' ? <div id="cortex-conversations-compact" className={compactLayout ? '' : 'xl:hidden'}><ApexConversationRail className="block w-full border-b border-r-0" /></div> : null}
    <div className={props.assistantRunConfig ? 'grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[14rem_minmax(0,1fr)_22rem]' : 'grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem]'}>{props.assistantRunConfig ? <ApexConversationRail className={compactLayout ? 'hidden' : 'hidden xl:block'} /> : null}<div className="order-1 flex min-h-0 flex-col">{props.assistantRunConfig ? (props.agentQueriesEnabled ? <ApexAssistantThread renderAgent={renderAssistantResponse} disabled={isQuerying || Boolean(props.submissionPending) || !props.selectionReady} /> : <footer className="border-t border-white/10 p-4 text-sm text-zinc-500">Agent queries are disabled in Settings.</footer>) : <><Conversation history={props.history} latestTrace={props.latestTrace} error={props.error} isQuerying={props.isQuerying} agentsStatus={props.agentsStatus} activeAgent={props.activeAgent} onPromptSelect={promptChipsEnabled ? (query) => { void props.onSubmit(query, props.activeAgent, props.selectedToolNames ?? [], props.activeToolProfileId ?? null) } : null} />{props.agentQueriesEnabled ? <footer className="border-t border-white/10 bg-black/20 p-3 sm:p-4"><AgentQueryBar presentation="cortex" activeAgent={props.activeAgent} onSubmit={props.onSubmit} agentsStatus={props.agentsStatus} catalog={props.toolCatalog ?? null} selectedToolNames={props.selectedToolNames ?? []} activeToolProfileId={props.activeToolProfileId ?? null} selectionReady={props.selectionReady ?? false} submissionPending={props.submissionPending} onToolSelectionChange={props.onToolSelectionChange} onToolProfileChange={props.onToolProfileChange} toolPreflight={props.toolPreflight} toolPreflightLoading={props.toolPreflightLoading} toolCatalogError={props.toolCatalogError} toolPreflightError={props.toolPreflightError} toolProfileFeedback={props.toolProfileFeedback} toolProfileError={props.toolProfileError} onSaveToolProfile={props.onSaveToolProfile} onDuplicateToolProfile={props.onDuplicateToolProfile} onRenameToolProfile={props.onRenameToolProfile} onDeleteToolProfile={props.onDeleteToolProfile} onRestoreToolProfile={props.onRestoreToolProfile} onSetDefaultToolProfile={props.onSetDefaultToolProfile} draftPrompt={props.draftPrompt} onDraftChange={props.onDraftChange} isSubmitting={props.isQuerying} error={props.error} /></footer> : null}</>}</div>
      <aside id="cortex-inspector-compact" className={`order-2 space-y-4 border-t border-white/10 bg-black/15 p-4 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:border-t-0 scrollbar-thin ${props.assistantRunConfig && compactPanel !== 'inspector' ? (compactLayout ? 'hidden' : 'hidden xl:block') : ''}`} aria-label="Cortex inspector"><section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Agent</p><AgentSelector activeAgent={props.activeAgent} onChange={props.onAgentChange} agentsStatus={props.agentsStatus} agentsStatusHydrated={props.agentsStatusHydrated} isQuerying={props.isQuerying || Boolean(props.submissionPending)} verifyingAgent={props.verifyingCloudAgent} onVerify={props.onVerifyCloudAgent} /></section>
        <RuntimeControls {...props} activeStatus={activeStatus ?? null} localContextLocked={localContextLocked} />
        <ContextControl {...props} />
        <CortexActions actions={props.actions} demoModeActive={props.demoModeActive} />
      </aside>
    </div>
  </section></AssistantBoundary>
}

function RuntimeControls({
  activeAgent,
  activeStatus,
  localContextLocked,
  ...props
}: CortexWorkspaceProps & {
  activeStatus: AgentStatus | null
  localContextLocked: boolean
}): ReactElement {
  const localModel = props.felisModel ?? 'gemma-4-E2B-Q4_K_M.gguf'
  const onLocalModelChange = props.onFelisModelChange ?? (() => {})
  const pantheraStatus = props.agentsStatus.find((agent) => agent.key === 'panthera')
  const felisStatus = props.agentsStatus.find((agent) => agent.key === 'felis')
  const catalog = resolveModelCatalog(
    activeAgent === 'panthera' ? pantheraStatus : felisStatus,
  )
  const models = catalog.filter(
    (entry) => entry.runtime === (activeAgent === 'panthera' ? 'cloud' : 'local'),
  )
  const hostedCapabilities = hostedCapabilitiesForModel(
    activeAgent === 'panthera' ? props.pantheraModel : localModel,
    catalog,
  )

  const selectedModelEntry = models.find(
    (entry) => entry.model_id === (activeAgent === 'panthera' ? props.pantheraModel : localModel),
  )
  const reasoningOptions = selectedModelEntry?.reasoning_options ?? pantheraStatus?.reasoning_options ?? []
  const supportsEffort = Boolean(reasoningOptions.length)

  return (
    <div className="space-y-4">
      {activeAgent === 'panthera' ? (
        <>
          <ModelSelector
            activeAgent="panthera"
            selectedModelId={props.pantheraModel}
            onModelChange={props.onPantheraModelChange}
            catalog={models}
            activeStatus={pantheraStatus ?? null}
            disabled={props.isQuerying}
            isQuerying={props.isQuerying}
            verifyingAgent={props.verifyingCloudAgent}
            onVerify={props.onVerifyCloudAgent}
          />
          {supportsEffort && reasoningOptions.length > 0 ? (
            <section className="space-y-2">
              <label htmlFor="cortex-effort" className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">
                Reasoning effort
              </label>
              <select
                id="cortex-effort"
                value={props.cloudEffort}
                onChange={(event) => props.onEffortChange(event.target.value as CloudEffort)}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF]"
              >
                {reasoningOptions.map((effort) => (
                  <option key={effort} value={effort}>
                    {formatReasoningLabel(effort)}
                  </option>
                ))}
              </select>
            </section>
          ) : null}
        </>
      ) : (
        <>
          <ModelSelector
            activeAgent="felis"
            selectedModelId={localModel}
            onModelChange={onLocalModelChange}
            catalog={models}
            activeStatus={felisStatus ?? null}
            disabled={props.isQuerying}
            isQuerying={props.isQuerying}
          />
          {activeStatus ? (
            <>
              {activeStatus.reasoning_mode_options && activeStatus.reasoning_mode_options.length > 1 ? (
                <LocalReasoningControl
                  key={`${activeStatus.key}-reasoning`}
                  agent={activeStatus}
                  disabled={props.isQuerying || Boolean(props.submissionPending)}
                  onChange={props.onLocalReasoningModeChange}
                />
              ) : null}
              {activeStatus.context_window_options?.length ? (
                <LocalContextControl
                  key={`${activeStatus.key}-context`}
                  agent={activeStatus}
                  disabled={localContextLocked}
                  onChange={props.onLocalContextWindowChange}
                />
              ) : null}
              <LocalModelLifecycle
                agent={activeStatus}
                busy={props.lifecycleBusy}
                actionPending={props.lifecycleActionPending}
                onLoad={props.onLoadLocalModel}
                onUnload={props.onUnloadLocalModel}
              />
            </>
          ) : null}
        </>
      )}

      {hostedCapabilities.length > 0 ? (
        <GroundingControls note="Apex Brave Search remains the standard search capability when connected.">
          {hostedCapabilities.includes('google_search') ? (
            <GroundingToggle
              label="Google Search"
              detail="Provider grounding for later requests"
              checked={props.pantheraHostedTools.google_search}
              onChange={(enabled) => props.onHostedToolChange('google_search', enabled)}
            />
          ) : null}
          {hostedCapabilities.includes('google_maps') ? (
            <GroundingToggle
              label="Google Maps"
              detail="Provider grounding for later requests"
              checked={props.pantheraHostedTools.google_maps}
              onChange={(enabled) => props.onHostedToolChange('google_maps', enabled)}
            />
          ) : null}
          {hostedCapabilities.includes('x_search') ? (
            <GroundingToggle
              label="X Search"
              detail="Provider grounding for later requests"
              checked={props.pantheraHostedTools.x_search}
              onChange={(enabled) => props.onHostedToolChange('x_search', enabled)}
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
  return <div className="space-y-4"><section className="space-y-2"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Context</p><label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span className="text-xs text-zinc-300">Current HUD snapshot</span><input type="checkbox" checked={props.snapshotAttached} disabled={!props.snapshotAvailable} onChange={(event) => props.onSnapshotAttachedChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label><p className="text-[11px] leading-relaxed text-zinc-500">{props.snapshotAttached && props.snapshotAvailable ? 'The current snapshot will be included with the next turn.' : 'No HUD context will be attached.'}</p></section><section className="space-y-2" aria-label="Selected tools summary"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Prompt tools</p><div className="rounded-lg border border-purple-300/15 bg-purple-950/10 p-3 font-mono text-[10px] text-zinc-400"><p className="text-zinc-200">{activeProfile?.name ?? 'Custom'} · {selectedNames.length} selected</p><p className="mt-1 text-zinc-500">{props.selectionReady ? 'Configured beside the prompt.' : 'Hydrating this Agent selection…'}</p>{props.toolCatalog?.provider_hosted_tools.length ? <p className="mt-1 text-cyan-200/80">Hosted grounding: {props.toolCatalog.provider_hosted_tools.join(', ')}</p> : <p className="mt-1 text-zinc-600">Hosted grounding is controlled separately.</p>}{unavailableCount > 0 ? <p className="mt-1 text-red-200">{unavailableCount} unavailable selection{unavailableCount === 1 ? '' : 's'} need removal.</p> : null}{props.contextUsage ? <p className="mt-2 text-zinc-600">Last local estimate: {formatNumber(props.contextUsage.estimated_prompt_tokens)}/{formatNumber(props.contextUsage.context_window)} tokens.</p> : null}{props.toolCatalogError ? <p className="mt-2 text-red-200" role="alert">{props.toolCatalogError}</p> : null}</div></section></div>
}
function GroundingToggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (enabled: boolean) => void }): ReactElement { return <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"><span><span className="block font-mono text-[10px] uppercase tracking-wider text-zinc-300">{label}</span><span className="block text-[11px] text-zinc-500">{detail} · {checked ? 'Enabled' : 'Disabled'}</span></span><input aria-label={`${label} grounding`} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[#0F4DB8]" /></label> }
function GroundingControls({ note, children }: { note: string; children: React.ReactNode }): ReactElement { return <section className="space-y-2" aria-label="Grounding"><p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Grounding</p>{children}<p className="text-[11px] leading-relaxed text-zinc-500">{note}</p></section> }
