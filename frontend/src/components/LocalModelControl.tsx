import { useCallback, useState, type ReactElement } from 'react'

import type { AgentProfileStatus } from '../types/telemetry'

function formatCountdown(seconds: number | null): string {
  if (seconds === null) return '--:--'
  const safe = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}

export function LocalModelControl({
  profile,
  loadingProfile,
  busy,
  onUnload,
}: {
  profile: AgentProfileStatus | null
  loadingProfile: AgentProfileStatus | null
  busy: boolean
  onUnload: () => Promise<boolean>
}): ReactElement | null {
  const [unloading, setUnloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const visibleProfile = loadingProfile ?? profile
  const loading = loadingProfile !== null

  const handleUnload = useCallback(async (): Promise<void> => {
    if (!profile || loading || busy || unloading) return
    setUnloading(true)
    setError(null)
    const succeeded = await onUnload()
    if (!succeeded) setError('Unload failed')
    setUnloading(false)
  }, [profile, loading, busy, unloading, onUnload])

  if (!visibleProfile) return null

  const disabled = loading || busy || unloading || profile === null
  const stateText = loading
    ? 'Loading local model…'
    : busy
      ? 'In use · auto-unload paused'
      : `Auto-unload in ${formatCountdown(profile?.idle_unload_remaining_seconds ?? null)}`

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
        aria-label={`Unload ${visibleProfile.display_name}`}
      >
        <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-orange-500 shadow-[0_0_8px_rgba(249,115,22,0.9)]" />
        {visibleProfile.display_name} · {loading ? 'Loading' : unloading ? 'Unloading' : 'Unload'}
      </button>
      <span className="font-mono text-[9px] uppercase tracking-wider text-orange-200/60">
        {stateText}
      </span>
      {error ? <span className="font-mono text-[9px] uppercase text-red-400">{error}</span> : null}
    </div>
  )
}
