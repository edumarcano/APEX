import type { ReactElement } from 'react'
import type { AgentStability } from '../types/telemetry'

export interface StabilityBadgeProps {
  stability?: AgentStability | string | null
  className?: string
}

export function StabilityBadge({
  stability,
  className = '',
}: StabilityBadgeProps): ReactElement | null {
  if (!stability || stability === 'stable') return null
  const experimental = stability === 'experimental'
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${
        experimental
          ? 'border-cyan-300/30 bg-cyan-400/10 text-cyan-200'
          : 'border-amber-300/30 bg-amber-400/10 text-amber-200'
      }${className ? ` ${className}` : ''}`}
    >
      {experimental ? 'Experimental' : 'Preview'}
    </span>
  )
}
