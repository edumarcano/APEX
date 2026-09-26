import { LayoutGrid, Sparkles } from 'lucide-react'
import type { ReactElement } from 'react'

interface StandbyActionsProps {
  onStartOverview: () => void
  onStartBriefing: () => void
  disabled?: boolean
  briefingDisabled?: boolean
  briefingLabel?: string
}

const ACTION_CLASS = 'group hud-command-surface inline-flex items-center gap-1.5 rounded-lg border px-4 py-2.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] backdrop-blur-md transition-[border-color,background-color,box-shadow,color] duration-300 motion-reduce:transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 sm:text-[11px]'
const DISABLED_CLASS = 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'

export function StandbyActions({
  onStartOverview,
  onStartBriefing,
  disabled = false,
  briefingDisabled = false,
  briefingLabel = 'Daily',
}: StandbyActionsProps): ReactElement {
  const isBriefingInteractive = !disabled && !briefingDisabled
  return (
    <div className="inline-flex items-center gap-2.5" data-slot="standby-actions">
      <button
        type="button"
        onClick={onStartOverview}
        disabled={disabled}
        aria-label="Start Overview"
        title="Collect current telemetry without running a model."
        className={`${ACTION_CLASS} focus-visible:outline-[#1F6FE5] ${disabled
          ? DISABLED_CLASS
          : 'border-[#0F4DB8]/60 bg-[#0F4DB8]/20 text-blue-100 shadow-[inset_0_1px_0_rgba(110,168,255,0.15)] hover:border-[#6EA8FF]/80 hover:bg-[#0F4DB8]/35 hover:text-white hover:shadow-[0_0_12px_rgba(15,77,184,0.35)]'}`}
      >
        <LayoutGrid className="size-3.5 shrink-0 text-[#6EA8FF]" aria-hidden />
        <span className="whitespace-nowrap">Overview</span>
      </button>
      <button
        type="button"
        onClick={onStartBriefing}
        disabled={!isBriefingInteractive}
        aria-label={`Start Briefing with ${briefingLabel}`}
        title={briefingDisabled && !disabled ? 'Briefings require an available model and no active briefing run.' : undefined}
        className={`${ACTION_CLASS} focus-visible:outline-[#F59E0B] ${!isBriefingInteractive
          ? DISABLED_CLASS
          : 'border-amber-400/25 bg-amber-950/20 text-amber-200 shadow-[inset_0_1px_0_rgba(251,191,36,0.1)] hover:border-amber-400/40 hover:bg-amber-400/15 hover:text-amber-100 hover:shadow-[0_0_12px_rgba(251,191,36,0.18)]'}`}
      >
        <Sparkles className="size-3.5 shrink-0 text-amber-300" aria-hidden />
        <span className="whitespace-nowrap">Briefing</span>
      </button>
    </div>
  )
}
