import { Check, ChevronDown, Cloud, Cpu, Loader2, ShieldCheck } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

import type { AgentStatus, AgentRuntime, AgentKey, AgentAvailabilityStatus } from '../types/telemetry'

import { AgentMark } from './AgentMark'

interface AgentSelectorProps {
  activeAgent: AgentKey
  onChange: (agent: AgentKey) => void
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isQuerying: boolean
  verifyingAgent: AgentKey | null
  onVerify: (agent: Exclude<AgentKey, 'mus' | 'sorex'>) => Promise<boolean>
  presentation?: 'cortex' | 'home'
}

const STATUS_LABELS: Record<AgentAvailabilityStatus, string> = {
  available: 'Available', busy: 'Busy', configured: 'Configured', verifying: 'Verifying access',
  verified: 'Verified', unauthorized: 'Access denied', model_unavailable: 'Model unavailable',
  rate_limited: 'Rate limited', quota_exhausted: 'Quota exhausted', billing_blocked: 'Billing blocked',
  provider_unreachable: 'Provider unreachable', provider_error: 'Provider error', unknown: 'Checking availability',
  disabled: 'Unavailable', ollama_unreachable: 'Ollama unavailable', model_not_installed: 'Not installed',
  insufficient_ram: 'Insufficient memory', cpu_overloaded: 'CPU busy',
}

function agentRuntime(agent: AgentKey): AgentRuntime {
  return agent === 'mus' || agent === 'sorex' ? 'local' : 'cloud'
}

function fallbackName(agent: AgentKey): string {
  return `APEX ${agent.slice(0, 1).toUpperCase()}${agent.slice(1)}`
}

function formatModel(model: string): string {
  return model
    .replace(/^gpt-(\d+\.\d+)-(.+)$/i, (_, version: string, variant: string) => `GPT-${version} ${variant}`)
    .replace(/^gemini-(\d+\.\d+)-(.+)$/i, (_, version: string, variant: string) => `Gemini ${version} ${variant}`)
    .replace(/^grok-(\d+\.\d+)$/i, (_, version: string) => `Grok ${version}`)
    .replace(/^qwen(\d+):(\d+)b-(.+)$/i, (_, generation: string, size: string, variant: string) => `Qwen${generation} ${size}B ${variant}`)
    .split(/[-\s]/)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(' ')
}

function poweredBy(agent: AgentStatus): string {
  const suffix = agent.provider === 'ollama' ? ' Ãƒâ€šÃ‚Â· Runs locally through Ollama' : ''
  return `Powered by ${formatModel(agent.configured_model)}${suffix}`
}

function statusClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') return 'text-emerald-300'
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') return 'text-amber-200'
  return 'text-[#DC2626]'
}

function statusDotClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') {
    return 'bg-emerald-300 shadow-[0_0_7px_rgba(110,231,183,0.8)]'
  }
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') {
    return 'bg-amber-300 shadow-[0_0_7px_rgba(252,211,77,0.7)]'
  }
  if (status === 'disabled') {
    return 'bg-zinc-500 shadow-[0_0_5px_rgba(161,161,170,0.35)]'
  }
  return 'bg-[#DC2626] shadow-[0_0_7px_rgba(220,38,38,0.8)]'
}

function rate(value: number): string { return `$${value.toFixed(2)}/1M` }

function popoverPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(440, window.innerWidth - 24)
  return {
    bottom: window.innerHeight - rect.top + 8,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    width,
  }
}

export function AgentSelector({
  activeAgent, onChange, agentsStatus, agentsStatusHydrated,
  isQuerying, verifyingAgent, onVerify, presentation = 'cortex',
}: AgentSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [browseMode, setBrowseMode] = useState<AgentRuntime>(() => agentRuntime(activeAgent))
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const activeStatus = agentsStatus.find((agent) => agent.key === activeAgent)
  const home = presentation === 'home'

  const agents = useMemo(() => agentsStatus
    .filter((agent) => agent.runtime === browseMode)
    .sort((left, right) => left.sort_order - right.sort_order), [browseMode, agentsStatus])
  const homeAgents = useMemo(() => agentsStatus
    .sort((left, right) => left.sort_order - right.sort_order), [agentsStatus])

  useEffect(() => {
    if (!isOpen) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (!popoverRef.current?.contains(target) && !triggerRef.current?.contains(target)) setIsOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setIsOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    const focusTimer = window.setTimeout(() => popoverRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus(), 0)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
      window.clearTimeout(focusTimer)
    }
  }, [isOpen])

  const updatePosition = useCallback((): void => {
    if (home && triggerRef.current) setPosition(popoverPosition(triggerRef.current))
  }, [home])

  useLayoutEffect(() => {
    if (!isOpen || !home) return
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, home, updatePosition])

  const selectAgent = (agent: AgentKey): void => {
    onChange(agent)
    setIsOpen(false)
    window.setTimeout(() => triggerRef.current?.focus(), 0)
  }

  const handleTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>): void => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const nextMode: AgentRuntime = browseMode === 'cloud' ? 'local' : 'cloud'
    setBrowseMode(nextMode)
    window.setTimeout(() => popoverRef.current?.querySelector<HTMLButtonElement>(`button[role="tab"][data-mode="${nextMode}"]`)?.focus(), 0)
  }

  const renderCard = (agent: AgentStatus): ReactElement => {
    const selected = agent.key === activeAgent
    const isCloud = agent.runtime === 'cloud'
    const selectable = isCloud ? agent.status !== 'disabled' : agent.status === 'available'
    const verifyPending = verifyingAgent === agent.key || agent.status === 'verifying'
    return <article key={agent.key} className={`rounded-xl border p-3 ${selected ? 'border-[#7E22CE]/55 bg-[#7E22CE]/12' : 'border-white/10 bg-white/[0.02]'}`}>
      <button type="button" disabled={!selectable} aria-pressed={selected} aria-label={`Use ${agent.display_name}`} onClick={() => selectAgent(agent.key)} className={`w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${!selectable ? 'cursor-not-allowed opacity-55' : ''}`}>
        <span className="flex items-start gap-3"><AgentMark agent={agent.key} size="card" /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{agent.display_name}</span>{selected ? <Check className="size-4 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}</span><span className="mt-1 block text-xs leading-relaxed text-zinc-400">{agent.description}</span></span></span>
        <span className="mt-3 block border-t border-white/10 pt-2 font-mono text-[10px] text-zinc-400">{poweredBy(agent)}</span>
        <span className="mt-2 flex flex-wrap items-center gap-1.5">{agent.capabilities.map((capability) => <span key={capability} className="rounded border border-white/10 bg-black/20 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400">{capability}</span>)}<span className={`ml-auto inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider ${statusClass(agent.status)}`}>{agent.status === 'unknown' || verifyPending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}{STATUS_LABELS[agent.status]}</span></span>
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-white/10 pt-2"><span className="font-mono text-[9px] text-zinc-500">{agent.pricing.billing_basis === 'free_tier' ? 'Free tier' : agent.pricing.billing_basis === 'local' ? 'No provider token charge' : `In ${rate(agent.pricing.input_per_million)} Ãƒâ€šÃ‚Â· Out ${rate(agent.pricing.output_per_million)}`}</span>{agent.pricing.long_context_threshold_tokens ? <span className="font-mono text-[9px] text-zinc-600">Higher long-context rates may apply</span> : null}{isCloud ? <button type="button" disabled={!selectable || Boolean(verifyingAgent) || isQuerying} onClick={() => void onVerify(agent.key as Exclude<AgentKey, 'mus' | 'sorex'>)} className="ml-auto inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/55 hover:text-white disabled:cursor-not-allowed disabled:opacity-45"><ShieldCheck className="size-3" aria-hidden />{verifyPending ? 'Verifying' : 'Verify access'}</button> : null}</div>
      {agent.reason ? <p className="mt-2 text-[10px] text-red-200">{agent.reason}</p> : null}
    </article>
  }

  const renderHomeOption = (agent: AgentStatus): ReactElement => {
    const selected = agent.key === activeAgent
    const selectable = agent.runtime === 'cloud' ? agent.status !== 'disabled' : agent.status === 'available'
    return <li key={agent.key} role="presentation">
      <button
        type="button"
        role="option"
        disabled={!selectable}
        aria-selected={selected}
        aria-label={`Use ${agent.display_name}`}
        onClick={() => selectAgent(agent.key)}
        className={`flex min-h-16 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none ${selected ? 'bg-[#7E22CE]/12 ring-1 ring-[#7E22CE]/35' : ''} ${selectable ? 'hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15' : 'cursor-not-allowed opacity-45'}`}
      >
        <AgentMark agent={agent.key} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">{agent.display_name.replace(/^Apex\\s+/i, '')}</span>
          <span className="mt-0.5 block truncate text-[10px] text-zinc-500">{agent.description}</span>
        </span>
        <span className={`shrink-0 font-mono text-[9px] uppercase tracking-wider ${statusClass(agent.status)}`}>{STATUS_LABELS[agent.status]}</span>
        {selected ? <Check className="size-3.5 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}
      </button>
      {!selectable && agent.reason ? <p className="px-2.5 pb-2 font-mono text-[9px] text-red-200">{agent.reason}</p> : null}
    </li>
  }

  const activeAvailability = activeStatus?.status ?? 'unknown'
  const activeName = activeStatus?.display_name ?? fallbackName(activeAgent)
  if (!agentsStatusHydrated && !activeStatus) {
    return <section aria-label="Agent selector" className={home ? 'flex h-10 w-full items-center rounded-lg border border-white/10 bg-black/25 px-3 font-mono text-[10px] text-zinc-500 sm:w-36' : 'rounded-xl border border-white/10 bg-white/[0.02] p-3 font-mono text-[10px] text-zinc-500'}>Loading agent catalogÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦</section>
  }
  const popover = isOpen ? home
    ? <div ref={popoverRef} id="home-agent-popover" role="dialog" aria-label="Select Agent" style={position ?? undefined} className="fixed z-[100] max-h-[min(62vh,32rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-2 shadow-2xl backdrop-blur-xl scrollbar-thin">
        <div className="border-b border-white/10 px-2 pb-2 pt-1">
          <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">Agent</p>
          <p className="mt-1 text-[10px] text-zinc-500">Applies to your next Ask APEX request.</p>
        </div>
        {(['cloud', 'local'] as const).map((mode) => {
          const modeAgents = homeAgents.filter((agent) => agent.runtime === mode)
          if (modeAgents.length === 0) return null
          const Icon = mode === 'cloud' ? Cloud : Cpu
          return <section key={mode} className="py-1.5" aria-label={`${mode === 'cloud' ? 'Cloud' : 'Local'} agents`}>
            <p className="flex items-center gap-2 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-zinc-500"><Icon className="size-3.5 text-zinc-600" aria-hidden />{mode}</p>
            <ul role="listbox" aria-label={`${mode === 'cloud' ? 'Cloud' : 'Local'} Agents`} className="space-y-1">{modeAgents.map(renderHomeOption)}</ul>
          </section>
        })}
      </div>
    : <div ref={popoverRef} id="cortex-agent-popover" role="dialog" aria-label="Select agent" className="absolute left-0 right-0 top-full z-40 mt-2 max-h-[min(62vh,38rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-3 shadow-2xl backdrop-blur-xl scrollbar-thin"><div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-black/30 p-1" role="tablist" aria-label="Agent runtime">{([['cloud', Cloud, 'Cloud agents'], ['local', Cpu, 'Local agents']] as const).map(([mode, Icon, label]) => <button key={mode} data-mode={mode} type="button" role="tab" aria-selected={browseMode === mode} onClick={() => setBrowseMode(mode)} onKeyDown={handleTabKeyDown} className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-2 font-mono text-[10px] uppercase tracking-wider ${browseMode === mode ? mode === 'cloud' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'bg-[#78350F]/25 text-[#FDBA74]' : 'text-zinc-500 hover:text-zinc-300'}`}><Icon className="size-3.5" aria-hidden />{label}</button>)}</div><div className="mt-3 space-y-2">{agents.map(renderCard)}</div></div>
    : null

  return <section aria-label="Agent selector" className={home ? 'relative w-full sm:w-auto' : 'relative'}>
    <button ref={triggerRef} type="button" aria-expanded={isOpen} aria-haspopup="dialog" aria-controls={home ? 'home-agent-popover' : 'cortex-agent-popover'} aria-label={home ? `Agent ${activeName.replace(/^Apex\\s+/i, '')}, ${STATUS_LABELS[activeAvailability]}` : undefined} title={home ? `${activeName.replace(/^Apex\\s+/i, '')}: ${STATUS_LABELS[activeAvailability]}` : undefined} onClick={() => { setBrowseMode(agentRuntime(activeAgent)); setIsOpen((open) => !open) }} className={home ? 'flex h-10 w-full items-center gap-2 rounded-lg border border-white/10 bg-black/25 px-3 text-left transition-colors hover:border-white/20 hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] sm:w-auto sm:min-w-36' : 'w-full rounded-xl border border-[#7E22CE]/45 bg-[#7E22CE]/10 p-3 text-left transition-colors hover:border-[#C084FC]/65 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]'}>{home ? <><AgentMark agent={activeAgent} /><span data-slot="home-agent-status-dot" data-status={activeAvailability} className={`size-1.5 shrink-0 rounded-full ${statusDotClass(activeAvailability)}`} aria-hidden /><span className="min-w-0 flex-1"><span className="block truncate font-mono text-[10px] uppercase tracking-wider text-zinc-200">{activeName.replace(/^Apex\\s+/i, '')}</span></span><ChevronDown className={`size-3.5 shrink-0 text-zinc-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden /></> : <><span className="flex items-center gap-3"><AgentMark agent={activeAgent} size="card" /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{activeName}</span><ChevronDown className={`size-4 shrink-0 text-[#D8B4FE] transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden /></span>{activeStatus ? <span className="mt-1 block font-mono text-[10px] text-zinc-400">{poweredBy(activeStatus)}</span> : null}</span></span><span className={`mt-2 block font-mono text-[9px] uppercase tracking-wider ${statusClass(activeAvailability)}`}>{STATUS_LABELS[activeAvailability]}</span></>}</button>
    {home ? popover && position ? createPortal(popover, document.body) : null : popover}
  </section>
}
