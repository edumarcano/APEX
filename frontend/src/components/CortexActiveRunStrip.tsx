import { Activity, Square } from 'lucide-react'
import { useEffect, useState } from 'react'

import { isRunActive } from '../hooks/useCortexRuns'
import type { RunRecord } from '../types/runs'

export interface CortexActiveRunStripProps {
  run: RunRecord | null
  onInspect?: () => void
  onCancel?: (runId: string) => Promise<boolean> | void
  className?: string
}

export function CortexActiveRunStrip({
  run,
  onInspect,
  onCancel,
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

  const tokens = run.total_tokens
  const statusColor =
    run.status === 'cancelling'
      ? 'border-red-500/40 bg-red-950/30 text-red-300'
      : run.status === 'queued'
        ? 'border-amber-500/40 bg-amber-950/30 text-amber-300'
        : 'border-cyan-500/40 bg-cyan-950/30 text-cyan-300'

  const dotColor =
    run.status === 'cancelling'
      ? 'bg-red-400'
      : run.status === 'queued'
        ? 'bg-amber-400'
        : 'bg-cyan-400'

  return (
    <aside
      aria-label="Active Cortex Run"
      aria-live="polite"
      data-testid="cortex-active-run-strip"
      className={`flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-white/10 bg-zinc-950/80 backdrop-blur text-xs font-mono ${className}`}
    >
      <div className="flex items-center gap-2.5 min-w-0 overflow-hidden">
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border uppercase tracking-wider text-[10px] font-semibold ${statusColor}`}
        >
          <span
            aria-hidden="true"
            className={`inline-block size-1.5 rounded-full ${dotColor} animate-pulse motion-reduce:animate-none`}
          />
          {run.status}
        </span>

        <span className="text-zinc-300 truncate font-sans text-xs">
          {run.resolved_model || run.requested_model}
        </span>

        <span className="text-zinc-500">|</span>

        <span className="text-zinc-400 tabular-nums">
          {formattedElapsed}
        </span>

        {tokens !== undefined && tokens > 0 && (
          <>
            <span className="text-zinc-500">|</span>
            <span className="text-zinc-400 tabular-nums">
              {tokens} tokens
            </span>
          </>
        )}
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        {onInspect && (
          <button
            type="button"
            onClick={onInspect}
            className="flex items-center gap-1 px-2 py-1 rounded border border-white/10 bg-zinc-900 text-zinc-300 hover:text-white hover:border-white/20 transition-colors text-[11px]"
            aria-label="Inspect run details"
          >
            <Activity className="size-3 text-cyan-400" aria-hidden="true" />
            <span>Inspect</span>
          </button>
        )}

        {onCancel && run.status !== 'cancelling' && (
          <button
            type="button"
            onClick={() => void onCancel(run.id)}
            className="flex items-center gap-1 px-2 py-1 rounded border border-red-500/30 bg-red-950/20 text-red-300 hover:bg-red-950/40 hover:border-red-500/50 transition-colors text-[11px]"
            aria-label="Stop run"
          >
            <Square className="size-2.5 fill-current" aria-hidden="true" />
            <span>Stop</span>
          </button>
        )}
      </div>
    </aside>
  )
}
