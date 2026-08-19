import { Check } from 'lucide-react'
import type { ReactElement } from 'react'

import type { AgentStatus, AgentKey } from '../types/telemetry'
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
}

const AGENT_TAGS: Record<string, string> = {
  panthera: 'Cloud · Generalist',
  felis: 'Local · Private',
}

export function AgentSelector({
  activeAgent,
  onChange,
  agentsStatus,
  agentsStatusHydrated,
  isQuerying,
}: AgentSelectorProps): ReactElement {
  const durableAgents: AgentKey[] = ['panthera', 'felis']

  if (!agentsStatusHydrated && agentsStatus.length === 0) {
    return (
      <section
        aria-label="Agent selector"
        className="rounded-xl border border-white/10 bg-white/[0.02] p-3 font-mono text-[10px] text-zinc-500"
      >
        Loading agent catalog…
      </section>
    )
  }

  return (
    <section aria-label="Agent selector" className="space-y-1.5">
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Execution boundary">
        {durableAgents.map((key) => {
          const status = agentsStatus.find((agent) => agent.key === key)
          const selected = key === activeAgent
          const selectable = status ? isAgentIdentitySelectable(status) : true
          const fullName = status?.display_name || (key === 'panthera' ? 'Apex Panthera' : 'Apex Felis')
          const tag = AGENT_TAGS[key] || (key === 'panthera' ? 'Cloud · Generalist' : 'Local · Private')

          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={`${fullName}, ${tag}`}
              disabled={!selectable || isQuerying}
              onClick={() => onChange(key)}
              className={`relative flex flex-col items-start gap-1.5 rounded-xl border p-3 text-left transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${
                selected
                  ? 'border-[#7E22CE]/65 bg-[#7E22CE]/15 shadow-[0_0_16px_rgba(126,34,206,0.25)]'
                  : 'border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]'
              } ${!selectable ? 'cursor-not-allowed opacity-45' : ''}`}
            >
              {selected ? (
                <Check className="absolute right-2.5 top-2.5 size-3.5 text-[#39FF88]" aria-hidden />
              ) : null}
              <div className="flex items-center gap-1.5 pr-4">
                <AgentMark agent={key} size="compact" />
                <span className="font-orbitron text-xs font-semibold uppercase tracking-[0.08em] text-white">
                  {fullName}
                </span>
              </div>
              <span className="text-[11px] leading-tight text-zinc-400">
                {tag}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
