import type { ReactElement } from 'react'

export function TelemetryCollectionAction({
  onCollect,
  label = 'Collect Telemetry',
  disabled = false,
}: {
  onCollect: () => void
  label?: string
  disabled?: boolean
}): ReactElement {
  return <button
    type="button"
    onClick={onCollect}
    disabled={disabled}
    className={`inline-flex items-center gap-2 rounded-lg border border-[#047857]/60 bg-[#047857]/25 px-4 py-2.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[#6EE7B7] shadow-[inset_0_1px_0_rgba(110,231,183,0.15)] transition-[border-color,background-color,box-shadow,color] duration-300 motion-reduce:transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#10B981] ${disabled
      ? 'cursor-not-allowed opacity-40'
      : 'hover:border-[#10B981]/80 hover:bg-[#047857]/40 hover:text-[#6EE7B7] hover:shadow-[0_0_12px_rgba(16,185,129,0.35)]'}`}
  >
    {label}
  </button>
}
