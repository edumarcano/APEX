import { Play, Sparkles } from 'lucide-react'
import { useState, type ReactElement } from 'react'

interface StandbyActionsProps {
  onStartApex: () => void
  onStartWithBriefing: () => void
  disabled?: boolean
}

export function StandbyActions({
  onStartApex,
  onStartWithBriefing,
  disabled = false,
}: StandbyActionsProps): ReactElement {
  const [hoveredButton, setHoveredButton] = useState<'primary' | 'secondary' | null>(null)
  const isInteractive = !disabled

  const primaryLabel =
    hoveredButton === 'primary' && isInteractive ? '> Start APEX' : 'Start APEX'
  const secondaryLabel =
    hoveredButton === 'secondary' && isInteractive
      ? '> Start with Briefing'
      : 'Start with Briefing'

  return (
    <div className="inline-flex items-center gap-2.5" data-slot="standby-actions">
      <button
        type="button"
        onClick={onStartApex}
        disabled={!isInteractive}
        aria-label="Start APEX"
        data-slot="standby-activate-trigger"
        onMouseEnter={() => setHoveredButton('primary')}
        onMouseLeave={() => setHoveredButton(null)}
        onFocus={() => setHoveredButton('primary')}
        onBlur={() => setHoveredButton(null)}
        className={`group hud-command-surface inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] transition-[border-color,background-color,box-shadow,color] duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1F6FE5] sm:text-[11px] ${
          disabled
            ? 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'
            : 'border-[#0F4DB8]/60 bg-[#0F4DB8]/20 text-blue-100 shadow-[inset_0_1px_0_rgba(110,168,255,0.15)] hover:border-[#6EA8FF]/80 hover:bg-[#0F4DB8]/35 hover:text-white hover:shadow-[0_0_12px_rgba(15,77,184,0.35)] active:bg-[#0F4DB8]/50 active:shadow-[0_0_6px_rgba(15,77,184,0.2)]'
        }`}
      >
        <Play className="size-3.5 fill-current shrink-0 text-[#6EA8FF] transition-transform group-hover:scale-110" aria-hidden />
        <span className="whitespace-nowrap">{primaryLabel}</span>
      </button>
      <button
        type="button"
        onClick={onStartWithBriefing}
        disabled={!isInteractive}
        aria-label="Start APEX with briefing"
        data-slot="standby-activate-with-briefing-trigger"
        onMouseEnter={() => setHoveredButton('secondary')}
        onMouseLeave={() => setHoveredButton(null)}
        onFocus={() => setHoveredButton('secondary')}
        onBlur={() => setHoveredButton(null)}
        className={`group hud-command-surface inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] transition-[border-color,background-color,box-shadow,color] duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F59E0B] sm:text-[11px] ${
          disabled
            ? 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'
            : 'border-amber-400/25 bg-amber-950/20 text-amber-200 shadow-[inset_0_1px_0_rgba(251,191,36,0.1)] hover:border-amber-400/40 hover:bg-amber-400/15 hover:text-amber-100 hover:shadow-[0_0_12px_rgba(251,191,36,0.18)] active:bg-amber-400/25 active:shadow-[0_0_6px_rgba(251,191,36,0.1)]'
        }`}
      >
        <Sparkles className="size-3.5 shrink-0 text-amber-300 transition-transform group-hover:scale-110" aria-hidden />
        <span className="whitespace-nowrap">{secondaryLabel}</span>
      </button>
    </div>
  )
}
