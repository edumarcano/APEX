import { BrainCircuit } from 'lucide-react'
import type { ReactElement } from 'react'

import type { AgentKey } from '../types/telemetry'

const APEX_MARK = {
  icon: BrainCircuit,
  label: 'Apex Agent mark',
  className: 'border-[#7E22CE]/35 bg-[#7E22CE]/15 text-[#D8B4FE]',
}

interface AgentMarkProps {
  agent: AgentKey
  size?: 'compact' | 'card'
}

export function AgentMark({ size = 'compact' }: AgentMarkProps): ReactElement {
  const mark = APEX_MARK
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
