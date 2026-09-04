import { Activity } from 'lucide-react'
import { useEffect, useState } from 'react'

import { isRunActive } from '../hooks/useCortexRuns'
import type { RunRecord } from '../types/runs'

export interface CortexActiveRunStripProps {
  run: RunRecord | null
  agentName?: string
  onInspect?: () => void
  className?: string
}

export function CortexActiveRunStrip({
  run,
  agentName = 'Agent',
  onInspect,
  className = '',
}: CortexActiveRunStripProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!run || !isRunActive(run.status)) return
    const timer = window.setInterval(() => {
      setNow(Date.now())
    }, 200)
    return () => window.clearInterval(timer)
  }, [run])

  if (!run || !isRunActive(run.status)) {
    return null
  }

  const startTime = run.started_at ? new Date(run.started_at).getTime() : new Date(run.created_at).getTime()
  const elapsedSeconds = Math.max(0, (now - startTime) / 1000)
  const formattedElapsed = `${elapsedSeconds.toFixed(1)}s`

  const dotColor =
    run.status === 'cancelling'
      ? 'bg-red-400'
      : run.status === 'queued'
        ? 'bg-amber-400'
        : 'bg-[#C084FC]'

  return (
    <div
      aria-label="Active Cortex Run"
      aria-live="polite"
      data-testid="cortex-active-run-strip"
      className={`flex items-center gap-2 font-mono text-xs tracking-wider text-zinc-400 ${className}`}
    >
      <span
        aria-hidden="true"
        className={`inline-block size-2 rounded-full ${dotColor} animate-pulse motion-reduce:animate-none`}
      />
      <span className="text-[#D8B4FE] uppercase font-semibold text-[11px]">
        {agentName} working
      </span>
      <span className="text-zinc-600">·</span>
      <span className="text-zinc-300 tabular-nums text-[11px]">
        {formattedElapsed}
      </span>
      {onInspect && (
        <button
          type="button"
          onClick={onInspect}
          className="text-zinc-400 hover:text-[#9AC2FF] transition-colors p-0.5 rounded hover:bg-white/5"
          aria-label="Inspect active run"
          title="Inspect run in Activity tab"
        >
          <Activity className="size-3.5" aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
