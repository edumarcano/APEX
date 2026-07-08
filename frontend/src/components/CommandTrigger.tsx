import { useState, type ReactElement } from 'react'

interface CommandTriggerProps {
  onClick: () => void
  disabled?: boolean
}

export function CommandTrigger({
  onClick,
  disabled = false,
}: CommandTriggerProps): ReactElement {
  const [isHovered, setIsHovered] = useState(false)
  const isInteractive = !disabled

  const label =
    isHovered && isInteractive
      ? '> INITIATE SYSTEM SYNTHESIS'
      : '[ INITIATE SYSTEM SYNTHESIS ]'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!isInteractive}
      aria-label="Initiate system synthesis"
      data-slot="synthesis-trigger"
      onMouseEnter={() => {
        setIsHovered(true)
      }}
      onMouseLeave={() => {
        setIsHovered(false)
      }}
      onFocus={() => {
        setIsHovered(true)
      }}
      onBlur={() => {
        setIsHovered(false)
      }}
      className={`hud-command-surface inline-flex rounded-md border px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] sm:text-[11px] ${
        disabled
          ? 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'
          : 'border-[#0F4DB8]/40 bg-[#0F4DB8]/10 text-[#FBBF24] shadow-[0_0_10px_rgba(15,77,184,0.2)] hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 hover:text-[#FBBF24]'
      }`}
    >
      {label}
    </button>
  )
}
