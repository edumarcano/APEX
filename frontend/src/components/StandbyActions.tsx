import { Radio } from 'lucide-react'
import type { ReactElement } from 'react'

interface StandbyActionsProps {
  onCollectTelemetry: () => void
  disabled?: boolean
}

const ACTION_CLASS = 'group hud-command-surface inline-flex items-center gap-1.5 rounded-lg border px-4 py-2.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] backdrop-blur-md transition-[border-color,background-color,box-shadow,color] duration-300 motion-reduce:transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 sm:text-[11px]'
const DISABLED_CLASS = 'cursor-not-allowed border-white/5 bg-transparent text-zinc-600 opacity-40'

export function StandbyActions({
  onCollectTelemetry,
  disabled = false,
}: StandbyActionsProps): ReactElement {
  return (
    <div className="inline-flex items-center gap-2.5" data-slot="standby-actions">
      <button
        type="button"
        onClick={onCollectTelemetry}
        disabled={disabled}
        aria-label="Collect Telemetry"
        title="Collect current telemetry without running a model."
        className={`${ACTION_CLASS} focus-visible:outline-[#10B981] ${disabled
          ? DISABLED_CLASS
          : 'border-[#047857]/60 bg-[#047857]/25 text-[#6EE7B7] shadow-[inset_0_1px_0_rgba(110,231,183,0.15)] hover:border-[#10B981]/80 hover:bg-[#047857]/40 hover:text-[#6EE7B7] hover:shadow-[0_0_12px_rgba(16,185,129,0.35)]'}`}
      >
        <Radio className="size-3.5 shrink-0 text-[#10B981]" aria-hidden />
        <span className="whitespace-nowrap">Collect Telemetry</span>
      </button>
    </div>
  )
}
