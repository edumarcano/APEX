import { Loader2 } from 'lucide-react'
import { useCallback, useState, type ReactElement } from 'react'

import type { AgentStatus } from '../types/telemetry'
import { agentShortName } from '../lib/agentDisplay'
import { formatContextWindowLabel, providerDisplayName } from '../lib/agents'

function formatCountdown(seconds: number | null): string {
  if (seconds === null) return '--:--'
  const safe = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}

function localRuntimeLabel(agent: AgentStatus, runtimeState: string): string {
  const parts = [
    agentShortName(agent.display_name),
    providerDisplayName(agent.provider),
  ]
  const contextLabel = formatContextWindowLabel(
    agent.loaded_model?.context_window ?? null,
  )
  if (contextLabel) {
    parts.push(contextLabel)
  }
  parts.push(runtimeState)
  return parts.join(' · ')
}

export function LocalModelControl({
  agent,
  loadingAgent,
  busy,
  onUnload,
  presentation = 'default',
}: {
  agent: AgentStatus | null
  loadingAgent: AgentStatus | null
  busy: boolean
  onUnload: () => Promise<boolean>
  presentation?: 'default' | 'rail'
}): ReactElement | null {
  const [unloading, setUnloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const visibleAgent = loadingAgent ?? agent
  const loading = loadingAgent !== null

  const handleUnload = useCallback(async (): Promise<void> => {
    if (!agent || loading || busy || unloading) return
    setUnloading(true)
    setError(null)
    const succeeded = await onUnload()
    if (!succeeded) setError('Unload failed')
    setUnloading(false)
  }, [agent, loading, busy, unloading, onUnload])

  if (!visibleAgent) return null

  const disabled = loading || busy || unloading || agent === null
  const stateText = loading
    ? 'Loading local model…'
    : busy
      ? 'In use · auto-unload paused'
      : `Auto-unload in ${formatCountdown(agent?.idle_unload_remaining_seconds ?? null)}`

  if (presentation === 'rail') {
    const runtimeState = loading ? 'Loading' : busy ? 'In use' : unloading ? 'Unloading' : 'Loaded'
    return (
      <div className="home-local-runtime flex min-w-0 items-center gap-3 rounded-lg border border-orange-500/25 bg-orange-950/10 px-3 py-2" data-slot="home-local-runtime">
        <span className="min-w-0 flex-1 font-mono text-[10px] text-orange-100">
          {localRuntimeLabel(visibleAgent, runtimeState)}
        </span>
        <button
          type="button"
          onClick={() => void handleUnload()}
          disabled={disabled}
          className="inline-flex h-8 shrink-0 items-center justify-center rounded-md border border-orange-500/40 bg-orange-950/20 px-3 font-mono text-[10px] uppercase tracking-wider text-orange-100 transition-colors hover:border-orange-300 hover:bg-orange-950/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 disabled:cursor-not-allowed disabled:opacity-45"
          aria-label={'Unload ' + visibleAgent.display_name}
        >
          {loading || unloading ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : 'Unload'}
        </button>
        {error ? <span className="sr-only" role="alert">{error}</span> : null}
      </div>
    )
  }
  return (
    <div className="mt-3 flex flex-col items-center gap-1" data-slot="local-model-control">
      <button
        type="button"
        onClick={() => void handleUnload()}
        disabled={disabled}
        className={[
          'group relative min-w-[15rem] rounded border border-orange-500/50 bg-orange-950/10 px-4 py-2',
          'font-mono text-[10px] uppercase tracking-[0.18em] text-orange-300',
          'shadow-[0_0_14px_rgba(249,115,22,0.2)] transition-all duration-300',
          'hover:border-orange-400 hover:bg-orange-950/25 hover:shadow-[0_0_20px_rgba(249,115,22,0.4)]',
          disabled ? 'cursor-not-allowed opacity-65' : 'cursor-pointer',
        ].join(' ')}
        aria-label={`Unload ${visibleAgent.display_name}`}
      >
        <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-orange-500 shadow-[0_0_8px_rgba(249,115,22,0.9)]" />
        {visibleAgent.display_name} · {loading ? 'Loading' : unloading ? 'Unloading' : 'Unload'}
      </button>
      <span className="font-mono text-[9px] uppercase tracking-wider text-orange-200/60">
        {stateText}
      </span>
      {error ? <span className="font-mono text-[9px] uppercase text-red-400">{error}</span> : null}
    </div>
  )
}
