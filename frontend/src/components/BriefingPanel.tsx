import type { ReactElement } from 'react'

import type { SystemState } from '../types/telemetry'

export type BriefingPanelProps = {
  briefing: string
  status: SystemState
  error: string | null
  isLoading: boolean
  isSpeaking: boolean
}

export function BriefingPanel({ briefing }: BriefingPanelProps): ReactElement {
  return (
    <div
      className="relative w-full overflow-hidden rounded-xl border border-amber-500/40 bg-zinc-950/60 shadow-[0_0_12px_rgba(251,191,36,0.1)] p-3 px-4 backdrop-blur-md transition-all duration-500"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="flex w-full items-center gap-4">
        <span className="relative flex size-2 shrink-0" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
          <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
        </span>
        <p className="flex-1 text-sm font-medium leading-relaxed text-zinc-100 max-h-16 overflow-y-auto pr-2 scrollbar-thin whitespace-pre-wrap break-words">
          {briefing.trim()}
        </p>
      </div>
    </div>
  )
}
