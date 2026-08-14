import { Check } from 'lucide-react'
import { useCallback, useState, type ReactElement } from 'react'

import type { ActiveReminder } from '../types/telemetry'

type ReminderListRowProps = {
  reminder: ActiveReminder
  index: number
  onMarkRead: (id: string) => void
}

export function ReminderListRow({
  reminder,
  index,
  onMarkRead,
}: ReminderListRowProps): ReactElement {
  const [isDismissing, setIsDismissing] = useState(false)

  const handleComplete = useCallback((): void => {
    if (isDismissing) return
    setIsDismissing(true)
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      onMarkRead(reminder.id)
    }
  }, [isDismissing, onMarkRead, reminder.id])

  const handleTransitionEnd = useCallback(
    (event: React.TransitionEvent<HTMLLIElement>): void => {
      if (!isDismissing || event.propertyName !== 'opacity') return
      onMarkRead(reminder.id)
    },
    [isDismissing, onMarkRead, reminder.id],
  )

  return (
    <li
      className={[
        'group overflow-hidden rounded-md border border-white/[0.06] bg-zinc-950/20 transition-all duration-300 ease-in-out hover:border-[#0F4DB8]/30 hover:bg-[#0F4DB8]/[0.06]',
        isDismissing ? 'max-h-0 opacity-0 py-0' : 'max-h-16 opacity-100',
      ].join(' ')}
      onTransitionEnd={handleTransitionEnd}
    >
      <div className="flex items-center gap-3 px-3 py-2">
        <span className="hud-log-index w-5 pt-0">
          {String(index).padStart(2, '0')}
        </span>
        <p className="min-w-0 flex-1 truncate text-sm leading-relaxed text-zinc-200">
          {reminder.note}
        </p>
        {reminder.source === 'local' ? (
          <span className={reminder.sync_state === 'unknown'
            ? 'rounded border border-amber-300/25 px-1.5 py-0.5 font-mono text-[9px] uppercase text-amber-200'
            : 'rounded border border-sky-300/20 px-1.5 py-0.5 font-mono text-[9px] uppercase text-sky-200'}>
            {reminder.sync_state === 'unknown' ? 'Review' : 'Pending'}
          </span>
        ) : null}
        <button
          type="button"
          onClick={handleComplete}
          disabled={isDismissing}
          className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/[0.08] bg-black/20 text-zinc-500 transition-colors hover:border-[#39FF88]/40 hover:bg-[#39FF88]/10 hover:text-[#39FF88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:pointer-events-none"
          aria-label={`Complete reminder ${reminder.id}`}
        >
          <Check
            className="size-4"
            strokeWidth={2.25}
            aria-hidden
          />
        </button>
      </div>
    </li>
  )
}
