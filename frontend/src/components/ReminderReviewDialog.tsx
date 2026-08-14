import { useMemo, useState, type ReactElement } from 'react'

import type { ActiveReminder } from '../types/telemetry'

export function ReminderReviewDialog({
  reminders,
  onClose,
  onSync,
  onDismissUnknown,
}: {
  reminders: ActiveReminder[]
  onClose: () => void
  onSync: (ids: string[]) => Promise<Array<{ id: string; outcome: string }>>
  onDismissUnknown: (id: string) => Promise<void>
}): ReactElement {
  const pending = useMemo(
    () => reminders.filter((item) => item.source === 'local' && item.sync_state === 'pending'),
    [reminders],
  )
  const unknown = useMemo(
    () => reminders.filter((item) => item.source === 'local' && item.sync_state === 'unknown'),
    [reminders],
  )
  const [selected, setSelected] = useState<string[]>(pending.map((item) => item.id))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<Array<{ id: string; outcome: string }>>([])
  const selectedPending = selected.filter((id) => pending.some((item) => item.id === id))

  const sync = async (): Promise<void> => {
    if (!selectedPending.length) return
    setBusy(true)
    setError(null)
    try {
      setResults(await onSync(selectedPending))
    } catch {
      setError('Could not synchronize the selected reminders.')
    } finally {
      setBusy(false)
    }
  }

  const dismiss = async (id: string): Promise<void> => {
    if (!window.confirm('Inspect Microsoft To Do before dismissing an uncertain reminder. Dismiss it from the local review queue?')) return
    setBusy(true)
    setError(null)
    try {
      await onDismissUnknown(id)
    } catch {
      setError('Could not dismiss this reminder.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[var(--z-overlay)] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Review local reminders"
    >
      <div className="w-full max-w-md rounded-xl border border-white/15 bg-zinc-950 p-4 shadow-2xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-orbitron text-xs uppercase tracking-[0.14em] text-zinc-100">
            Review local reminders
          </h2>
          <button type="button" onClick={onClose} className="text-xs text-zinc-400">
            Close
          </button>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-zinc-400">Selected pending reminders are created one at a time and verified in Microsoft To Do.</p>
        <div className="mt-3 space-y-2">
          {pending.map((item) => (
            <label key={item.id} className="flex gap-2 rounded border border-white/10 p-2 text-sm text-zinc-200">
              <input
                type="checkbox"
                checked={selectedPending.includes(item.id)}
                onChange={(event) => setSelected((current) => (
                  event.target.checked
                    ? [...current, item.id]
                    : current.filter((id) => id !== item.id)
                ))}
              />
              {item.note}
            </label>
          ))}
          {unknown.map((item) => (
            <div key={item.id} className="flex items-center gap-2 rounded border border-amber-300/20 p-2 text-sm text-amber-100">
              <span className="min-w-0 flex-1">{item.note}</span>
              <button type="button" disabled={busy} onClick={() => void dismiss(item.id)} className="text-xs underline">
                Dismiss
              </button>
            </div>
          ))}
        </div>
        {error ? <p role="alert" className="mt-3 text-xs text-red-300">{error}</p> : null}
        {results.length ? (
          <ul className="mt-3 space-y-1 text-xs text-zinc-400" aria-live="polite">
            {results.map((item) => <li key={item.id}>{item.id}: {item.outcome}</li>)}
          </ul>
        ) : null}
        <button
          type="button"
          disabled={busy || !selectedPending.length}
          onClick={() => void sync()}
          className="mt-4 rounded border border-[#7EB3FF]/30 bg-[#7EB3FF]/10 px-3 py-1.5 text-xs text-[#9AC2FF] disabled:opacity-50"
        >
          Sync selected
        </button>
      </div>
    </div>
  )
}
