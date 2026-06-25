import { useState, type ReactElement } from 'react'

type CommandTriggerStatus = 'idle' | 'loading'

interface CommandTriggerProps {
  status: CommandTriggerStatus
  onClick: () => void
  disabled?: boolean
}

export function CommandTrigger({
  status,
  onClick,
  disabled = false,
}: CommandTriggerProps): ReactElement {
  const [isHovered, setIsHovered] = useState(false)
  const isLoading = status === 'loading'
  const isInteractive = !isLoading && !disabled

  const label = isLoading
    ? '[ SYNTHESIS INITIALIZING ]'
    : isHovered && isInteractive
      ? '> INITIATE SYSTEM SYNTHESIS'
      : '[ INITIATE SYSTEM SYNTHESIS ]'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!isInteractive}
      aria-label="Initiate system synthesis"
      aria-busy={isLoading}
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
      className={`inline-flex rounded-xl border border-[#0F4DB8]/40 bg-[#0F4DB8]/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-[#FBBF24] transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] sm:text-[11px] ${
        isLoading
          ? 'cursor-not-allowed animate-[pulse_3s_ease-in-out_infinite] opacity-80'
          : disabled
            ? 'cursor-not-allowed opacity-40'
            : 'hover:border-[#0F4DB8]/60 hover:bg-[#0F4DB8]/20'
      }`}
    >
      {label}
    </button>
  )
}
