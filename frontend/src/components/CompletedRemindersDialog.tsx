import { RefreshCw, RotateCcw, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

import type {
  CompletedRemindersResult,
  ReminderTaskDetail,
  ReminderTaskMutationResult,
} from '../hooks/useApexData'
import { useFocusTrap } from '../hooks/useFocusTrap'

type CompletedRemindersDialogProps = {
  onClose: () => void
  onLoad: () => Promise<CompletedRemindersResult>
  onReopen: (request: { id: string; last_modified_at: string }) => Promise<ReminderTaskMutationResult>
}

function formatDateTime(value: ReminderTaskDetail['completed_at']): string | null {
  if (!value) return null
  return `${value.date_time.replace('T', ' ')} (${value.time_zone})`
}

export function CompletedRemindersDialog({
  onClose, onLoad, onReopen,
}: CompletedRemindersDialogProps): ReactElement {
  const [items, setItems] = useState<ReminderTaskDetail[]>([])
  const [sourceState, setSourceState] = useState<CompletedRemindersResult['source_state']>('unavailable')
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [reviewIds, setReviewIds] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const loadRequestRef = useRef(0)

  useFocusTrap(true, dialogRef)

  const load = useCallback(async (): Promise<void> => {
    const requestId = ++loadRequestRef.current
    setLoading(true)
    setError(null)
    try {
      const result = await onLoad()
      if (requestId !== loadRequestRef.current) return
      setItems(result.items)
      setSourceState(result.source_state)
    } catch (reason) {
      if (requestId !== loadRequestRef.current) return
      setItems([])
      setSourceState('unavailable')
      setError(reason instanceof Error ? reason.message : 'Could not load completed reminders.')
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false)
    }
  }, [onLoad])

  useEffect(() => {
    let cancelled = false
    const loadInitial = async (): Promise<void> => {
      if (!cancelled) await load()
    }
    void loadInitial()
    return () => {
      cancelled = true
      loadRequestRef.current += 1
    }
  }, [load])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && busyId === null) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busyId, onClose])

  const reopen = async (task: ReminderTaskDetail): Promise<void> => {
    if (busyId || reviewIds[task.id]) return
    setBusyId(task.id)
    setError(null)
    try {
      const result = await onReopen({ id: task.id, last_modified_at: task.last_modified_at })
      if (result.outcome === 'synced') {
        setItems((current) => current.filter((item) => item.id !== task.id))
      } else {
        setReviewIds((current) => ({ ...current, [task.id]: result.action_id }))
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reopen reminder task.')
    } finally {
      setBusyId(null)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[var(--z-overlay)] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="presentation" onClick={(event) => { if (event.target === event.currentTarget && busyId === null) onClose() }}>
      <div ref={dialogRef} className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-white/15 bg-zinc-950 p-4 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="completed-reminders-title" tabIndex={-1}>
        <header className="flex shrink-0 items-center justify-between gap-3">
          <h2 id="completed-reminders-title" className="font-orbitron text-xs uppercase tracking-[0.14em] text-zinc-100">Completed reminders</h2>
          <div className="flex items-center gap-2"><button type="button" onClick={() => void load()} disabled={loading || busyId !== null} aria-label="Refresh completed reminders" className="inline-flex size-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:opacity-50"><RefreshCw className={loading ? 'size-3.5 animate-spin' : 'size-3.5'} aria-hidden /></button><button type="button" onClick={onClose} disabled={busyId !== null} aria-label="Close completed reminders" className="inline-flex size-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:opacity-50"><X className="size-4" aria-hidden /></button></div>
        </header>
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin">
          {loading ? <p className="text-sm text-zinc-400">Loading completed reminders…</p> : null}
          {!loading && sourceState === 'unavailable' ? <p className="text-sm text-red-200">Completed reminders are unavailable. Connect Microsoft To Do and select a list.</p> : null}
          {!loading && sourceState === 'live' && items.length === 0 ? <p className="text-sm text-zinc-400">No completed reminders available.</p> : null}
          {!loading && sourceState === 'live' && items.length ? <ul className="space-y-2">{items.map((task) => {
            const completedAt = formatDateTime(task.completed_at)
            const reviewing = reviewIds[task.id]
            return <li key={task.id} className="rounded-md border border-white/10 bg-white/[0.03] p-3"><div className="flex items-start gap-3"><div className="min-w-0 flex-1"><p className="break-words text-sm text-zinc-100">{task.title}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-zinc-500">{completedAt ? `Completed ${completedAt}` : 'Completed'}{task.due ? ` · Due ${task.due.date_time} (${task.due.time_zone})` : ''} · {task.importance}</p>{reviewing ? <p className="mt-2 text-xs text-amber-200">Review Microsoft To Do before retrying. Action {reviewing}</p> : null}</div><button type="button" disabled={busyId !== null || Boolean(reviewing)} onClick={() => void reopen(task)} className="inline-flex shrink-0 items-center gap-1 rounded border border-[#7EB3FF]/30 bg-[#7EB3FF]/10 px-2 py-1.5 text-xs text-[#9AC2FF] disabled:opacity-50"><RotateCcw className="size-3.5" aria-hidden />{busyId === task.id ? 'Reopening…' : 'Reopen'}</button></div></li>
          })}</ul> : null}
          {error ? <p role="alert" className="mt-3 text-xs text-red-300">{error}</p> : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
