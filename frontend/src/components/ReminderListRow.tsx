import { Check, MoreHorizontal } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import type { ActiveReminder } from '../types/telemetry'

type ReminderListRowProps = {
  reminder: ActiveReminder
  index: number
  onMarkRead: (id: string) => void
  onEdit?: (id: string) => void
  onDelete?: (id: string) => void
}

export function ReminderListRow({
  reminder,
  index,
  onMarkRead,
  onEdit,
  onDelete,
}: ReminderListRowProps): ReactElement {
  const [isDismissing, setIsDismissing] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: PointerEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

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
        'group relative rounded-md border border-white/[0.06] bg-zinc-950/20 transition-all duration-300 ease-in-out hover:border-[#0F4DB8]/30 hover:bg-[#0F4DB8]/[0.06]',
        isDismissing
          ? 'max-h-0 overflow-hidden opacity-0 py-0'
          : 'max-h-16 overflow-visible opacity-100',
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
        {reminder.source === 'todo' && onEdit && onDelete ? (
          <div ref={menuRef} className="relative shrink-0">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              disabled={isDismissing}
              aria-label={`Manage reminder ${reminder.id}`}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              className="flex size-7 items-center justify-center rounded-md border border-white/[0.08] bg-black/20 text-zinc-500 transition-colors hover:border-[#7EB3FF]/40 hover:bg-[#7EB3FF]/10 hover:text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:pointer-events-none"
            >
              <MoreHorizontal className="size-4" aria-hidden />
            </button>
            {menuOpen ? (
              <div role="menu" aria-label={`Reminder actions for ${reminder.note}`} className="absolute right-0 top-8 z-20 w-28 rounded-md border border-white/15 bg-zinc-950 p-1 shadow-xl">
                <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onEdit(reminder.id) }} className="block w-full rounded px-2 py-1.5 text-left text-xs text-zinc-200 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--hud-accent)]">Edit</button>
                <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onDelete(reminder.id) }} className="block w-full rounded px-2 py-1.5 text-left text-xs text-red-200 hover:bg-red-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300">Delete</button>
              </div>
            ) : null}
          </div>
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
