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
    hoveredButton === 'primary' && isInteractive ? '> START APEX' : '[ START APEX ]'
  const secondaryLabel =
    hoveredButton === 'secondary' && isInteractive
      ? '> START WITH BRIEFING'
      : '[ START WITH BRIEFING ]'

  return (
    <div className="inline-flex items-center gap-2" data-slot="standby-actions">
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
        className={`hud-command-surface inline-flex rounded-md border px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] sm:text-[11px] ${
          disabled
            ? 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'
            : 'border-[#0F4DB8]/40 bg-[#0F4DB8]/10 text-[#FBBF24] shadow-[0_0_10px_rgba(15,77,184,0.2)] hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 hover:text-[#FBBF24]'
        }`}
      >
        {primaryLabel}
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
        className={`hud-command-surface inline-flex rounded-md border px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] sm:text-[11px] ${
          disabled
            ? 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'
            : 'border-white/10 bg-white/5 text-[color:var(--hud-text)] hover:border-white/20 hover:bg-white/10'
        }`}
      >
        {secondaryLabel}
      </button>
    </div>
  )
}
