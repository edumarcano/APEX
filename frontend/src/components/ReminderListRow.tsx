import { Check } from 'lucide-react'
import { useCallback, useState, type ReactElement } from 'react'

import type { ActiveReminder } from '../types/telemetry'

type ReminderListRowProps = {
  reminder: ActiveReminder
  onMarkRead: (id: number) => void
}

export function ReminderListRow({
  reminder,
  onMarkRead,
}: ReminderListRowProps): ReactElement {
  const [isDismissing, setIsDismissing] = useState(false)

  const handleComplete = useCallback((): void => {
    if (isDismissing) return
    setIsDismissing(true)
  }, [isDismissing])

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
        'overflow-hidden rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 backdrop-blur-sm transition-all duration-300 ease-in-out',
        isDismissing ? 'max-h-0 opacity-0 py-0' : 'max-h-32 opacity-100',
      ].join(' ')}
      onTransitionEnd={handleTransitionEnd}
    >
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
          {reminder.note}
        </p>
        <button
          type="button"
          onClick={handleComplete}
          disabled={isDismissing}
          className="group flex size-8 shrink-0 items-center justify-center rounded-full border border-[color:var(--hud-accent)]/60 bg-black/30 text-[color:var(--hud-accent)] transition-colors hover:border-[color:var(--hud-accent)] hover:bg-[color:var(--hud-accent)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:pointer-events-none"
          aria-label={`Mark reminder ${reminder.id} as read`}
        >
          <Check
            className="size-4 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100"
            strokeWidth={2.25}
            aria-hidden
          />
        </button>
      </div>
    </li>
  )
}
