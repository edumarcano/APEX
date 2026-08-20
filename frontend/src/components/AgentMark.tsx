import { Network, MemoryStick } from 'lucide-react'
import type { ReactElement } from 'react'

import type { AgentKey } from '../types/telemetry'

const AGENT_MARKS: Record<string, { icon: typeof Network; label: string; className: string }> = {
  panthera: { icon: Network, label: 'Panthera agent mark', className: 'border-purple-300/25 bg-purple-400/10 text-purple-200' },
  felis: { icon: MemoryStick, label: 'Felis agent mark', className: 'border-amber-300/25 bg-amber-400/10 text-amber-200' },
}

interface AgentMarkProps {
  agent: AgentKey
  size?: 'compact' | 'card'
}

export function AgentMark({ agent, size = 'compact' }: AgentMarkProps): ReactElement {
  const mark = AGENT_MARKS[agent]
  const Icon = mark.icon
  return (
    <span
      aria-label={mark.label}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg border ${mark.className} ${size === 'card' ? 'size-10' : 'size-6'}`}
    >
      <Icon className={size === 'card' ? 'size-5' : 'size-3.5'} aria-hidden />
    </span>
  )
}
