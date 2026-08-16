import { Check, ChevronDown } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

import type { AgentStatus, AgentKey, AgentAvailabilityStatus } from '../types/telemetry'
import { agentShortName } from '../lib/agentDisplay'
import { isAgentIdentitySelectable } from '../lib/agents'

import { AgentMark } from './AgentMark'

interface AgentSelectorProps {
  activeAgent: AgentKey
  onChange: (agent: AgentKey) => void
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isQuerying: boolean
  verifyingAgent?: AgentKey | null
  onVerify?: (agent: 'panthera') => Promise<boolean>
  presentation?: 'cortex' | 'home'
}

const AGENT_SUBTITLES: Record<AgentKey, string> = {
  panthera: 'Cloud intelligence',
  lynx: 'Private on-device',
}

const AGENT_TAGS: Record<AgentKey, string> = {
  panthera: 'Cloud · Generalist',
  lynx: 'Local · Private',
}

const STATUS_LABELS: Record<AgentAvailabilityStatus, string> = {
  available: 'Available', busy: 'Busy', configured: 'Configured', verifying: 'Verifying access',
  verified: 'Verified', unauthorized: 'Access denied', model_unavailable: 'Model unavailable',
  rate_limited: 'Rate limited', quota_exhausted: 'Quota exhausted', billing_blocked: 'Billing blocked',
  provider_unreachable: 'Provider unreachable', provider_error: 'Provider error', unknown: 'Checking availability',
  disabled: 'Unavailable', ollama_unreachable: 'Ollama unavailable', model_not_installed: 'Not installed',
  insufficient_ram: 'Insufficient memory', cpu_overloaded: 'CPU busy',
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

function popoverPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(360, window.innerWidth - 24)
  return {
    bottom: window.innerHeight - rect.top + 8,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    width,
  }
}

export function AgentSelector({
  activeAgent,
  onChange,
  agentsStatus,
  agentsStatusHydrated,
  isQuerying,
  presentation = 'cortex',
}: AgentSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const activeStatus = agentsStatus.find((agent) => agent.key === activeAgent)
  const home = presentation === 'home'

  const agents = useMemo(
    () => [...agentsStatus].sort((left, right) => left.sort_order - right.sort_order),
    [agentsStatus],
  )

  useEffect(() => {
    if (!isOpen) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (!popoverRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setIsOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setIsOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    const focusTimer = window.setTimeout(
      () => popoverRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus(),
      0,
    )
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

  // --- Cortex Presentation: Compact 2-choice segmented selector ---
  if (!home) {
    if (!agentsStatusHydrated && agents.length === 0) {
      return (
        <section aria-label="Agent selector" className="rounded-xl border border-white/10 bg-white/[0.02] p-3 font-mono text-[10px] text-zinc-500">
          Loading agent catalog…
        </section>
      )
    }

    const durableAgents: AgentKey[] = ['panthera', 'lynx']

    return (
      <section aria-label="Agent selector" className="space-y-1.5">
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Execution boundary">
          {durableAgents.map((key) => {
            const status = agentsStatus.find((agent) => agent.key === key)
            const selected = key === activeAgent
            const selectable = status ? isAgentIdentitySelectable(status) : true
            const name = status ? agentShortName(status.display_name) : key === 'panthera' ? 'Panthera' : 'Lynx'
            const subtitle = AGENT_SUBTITLES[key]
            const tag = AGENT_TAGS[key]

            return (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={`${name}, ${subtitle}`}
                disabled={!selectable || isQuerying}
                onClick={() => onChange(key)}
                className={`relative flex flex-col items-start gap-1.5 rounded-xl border p-3 text-left transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${
                  selected
                    ? 'border-[#7E22CE]/65 bg-[#7E22CE]/15 shadow-[0_0_16px_rgba(126,34,206,0.25)]'
                    : 'border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]'
                } ${!selectable ? 'cursor-not-allowed opacity-45' : ''}`}
              >
                <div className="flex w-full items-center justify-between gap-1.5">
                  <div className="flex items-center gap-2">
                    <AgentMark agent={key} size="compact" />
                    <span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">
                      {name}
                    </span>
                  </div>
                  {selected ? (
                    <Check className="size-3.5 shrink-0 text-[#39FF88]" aria-hidden />
                  ) : null}
                </div>
                <span className="text-[11px] leading-tight text-zinc-400">
                  {subtitle}
                </span>
                <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">
                  {tag}
                </span>
              </button>
            )
          })}
        </div>
      </section>
    )
  }

  // --- Home Presentation: Compact Dropdown Trigger & Popover ---
  const activeAvailability = activeStatus?.status ?? 'unknown'
  const activeName = activeStatus ? agentShortName(activeStatus.display_name) : activeAgent === 'panthera' ? 'Panthera' : 'Lynx'

  const renderHomeOption = (agent: AgentStatus): ReactElement => {
    const selected = agent.key === activeAgent
    const selectable = isAgentIdentitySelectable(agent)
    const shortName = agentShortName(agent.display_name)
    const subtitle = AGENT_SUBTITLES[agent.key] ?? agent.description

    return (
      <li key={agent.key} role="presentation">
        <button
          type="button"
          role="option"
          disabled={!selectable}
          aria-selected={selected}
          aria-label={`Use ${agent.display_name}`}
          onClick={() => selectAgent(agent.key)}
          className={`flex min-h-14 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none ${
            selected ? 'bg-[#7E22CE]/12 ring-1 ring-[#7E22CE]/35' : ''
          } ${selectable ? 'hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15' : 'cursor-not-allowed opacity-45'}`}
        >
          <AgentMark agent={agent.key} />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">
              {shortName}
            </span>
            <span className="mt-0.5 block truncate text-[10px] text-zinc-500">
              {subtitle}
            </span>
          </span>
          <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">
            {agent.runtime === 'cloud' ? 'Cloud' : 'Local'}
          </span>
          {selected ? <Check className="size-3.5 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}
        </button>
      </li>
    )
  }

  const popover = isOpen && (
    <div
      ref={popoverRef}
      id="home-agent-popover"
      role="dialog"
      aria-label="Select Agent"
      style={position ?? undefined}
      className="fixed z-[100] max-h-[min(62vh,32rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-2 shadow-2xl backdrop-blur-xl scrollbar-thin"
    >
      <div className="border-b border-white/10 px-2 pb-2 pt-1">
        <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">
          Agent
        </p>
        <p className="mt-1 text-[10px] text-zinc-500">
          Applies to your next Agent query.
        </p>
      </div>
      <ul role="listbox" aria-label="Agents" className="space-y-1 py-1.5">
        {agents.map(renderHomeOption)}
      </ul>
    </div>
  )

  return (
    <section aria-label="Agent selector" className="relative w-full sm:w-auto">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-controls="home-agent-popover"
        aria-label={`Agent ${activeName}, ${STATUS_LABELS[activeAvailability]}`}
        title={`${activeName}: ${STATUS_LABELS[activeAvailability]}`}
        onClick={() => setIsOpen((open) => !open)}
        className="flex h-10 w-full items-center gap-2 rounded-lg border border-white/10 bg-black/25 px-3 text-left transition-colors hover:border-white/20 hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] sm:w-auto sm:min-w-36"
      >
        <AgentMark agent={activeAgent} />
        <span
          data-slot="home-agent-status-dot"
          data-status={activeAvailability}
          className={`size-1.5 shrink-0 rounded-full ${statusDotClass(activeAvailability)}`}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="truncate font-mono text-[10px] uppercase tracking-wider text-zinc-200">
            {activeName}
          </span>
        </span>
        <ChevronDown
          className={`size-3.5 shrink-0 text-zinc-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          aria-hidden
        />
      </button>
      {popover && position ? createPortal(popover, document.body) : null}
    </section>
  )
}
