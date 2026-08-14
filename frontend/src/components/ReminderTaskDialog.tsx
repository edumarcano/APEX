import { X } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

import type {
  ReminderTaskDetail,
  ReminderTaskMutationResult,
  ReminderTaskUpdateRequest,
} from '../hooks/useApexData'
import { useFocusTrap } from '../hooks/useFocusTrap'

type ReminderTaskDialogProps = {
  id: string
  mode: 'edit' | 'delete'
  onClose: () => void
  onLoad: (id: string) => Promise<ReminderTaskDetail>
  onUpdate: (request: ReminderTaskUpdateRequest) => Promise<ReminderTaskMutationResult>
  onDelete: (request: { id: string; last_modified_at: string }) => Promise<ReminderTaskMutationResult>
}

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

function inputDateTime(value: string): string {
  return value.replace(/(Z|[+-]\d\d:\d\d)$/, '').slice(0, 16)
}

function requestDateTime(value: string): string {
  return value.length === 16 ? `${value}:00` : value
}

export function ReminderTaskDialog({
  id, mode, onClose, onLoad, onUpdate, onDelete,
}: ReminderTaskDialogProps): ReactElement {
  const [task, setTask] = useState<ReminderTaskDetail | null>(null)
  const [title, setTitle] = useState('')
  const [importance, setImportance] = useState<ReminderTaskDetail['importance']>('normal')
  const [hasDue, setHasDue] = useState(false)
  const [dueValue, setDueValue] = useState('')
  const [timeZone, setTimeZone] = useState('UTC')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  useFocusTrap(true, dialogRef)

  useEffect(() => {
    let cancelled = false
    void onLoad(id).then((loaded) => {
      if (cancelled) return
      setTask(loaded)
      setTitle(loaded.title)
      setImportance(loaded.importance)
      setHasDue(loaded.due !== null)
      setDueValue(loaded.due ? inputDateTime(loaded.due.date_time) : '')
      setTimeZone(loaded.due?.time_zone || browserTimeZone())
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not load reminder task.')
    })
    return () => { cancelled = true }
  }, [id, onLoad])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busy, onClose])

  const changes = useMemo((): Omit<ReminderTaskUpdateRequest, 'id' | 'last_modified_at'> | null => {
    if (!task) return null
    if (!title.trim()) return null
    const next: Omit<ReminderTaskUpdateRequest, 'id' | 'last_modified_at'> = {}
    if (title.trim() !== task.title) next.title = title.trim()
    const originalDue = task.due ? inputDateTime(task.due.date_time) : ''
    if (!hasDue && task.due) {
      next.due = null
    } else if (hasDue && (task.due === null || dueValue !== originalDue)) {
      if (!dueValue) return null
      next.due = { date_time: requestDateTime(dueValue), time_zone: timeZone }
    }
    if (importance !== task.importance) next.importance = importance
    return Object.keys(next).length ? next : null
  }, [dueValue, hasDue, importance, task, timeZone, title])

  const submitEdit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    if (!task || !changes || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await onUpdate({ id: task.id, last_modified_at: task.last_modified_at, ...changes })
      if (result.outcome === 'synced') {
        onClose()
      } else {
        setError(`Microsoft To Do outcome is uncertain. Review action ${result.action_id} before trying again.`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update reminder task.')
    } finally {
      setBusy(false)
    }
  }

  const submitDelete = async (): Promise<void> => {
    if (!task || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await onDelete({ id: task.id, last_modified_at: task.last_modified_at })
      if (result.outcome === 'synced') {
        onClose()
      } else {
        setError(`Microsoft To Do outcome is uncertain. Review action ${result.action_id} before trying again.`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not delete reminder task.')
    } finally {
      setBusy(false)
    }
  }

  const closeOnBackdrop = useCallback((event: React.MouseEvent<HTMLDivElement>): void => {
    if (!busy && event.target === event.currentTarget) onClose()
  }, [busy, onClose])

  const label = mode === 'edit' ? 'Edit reminder' : 'Delete reminder'
  return createPortal(
    <div
      className="fixed inset-0 z-[var(--z-overlay)] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={closeOnBackdrop}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-xl border border-white/15 bg-zinc-950 p-4 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reminder-task-dialog-title"
        tabIndex={-1}
      >
        <header className="flex items-center justify-between gap-3">
          <h2 id="reminder-task-dialog-title" className="font-orbitron text-xs uppercase tracking-[0.14em] text-zinc-100">
            {label}
          </h2>
          <button type="button" onClick={onClose} disabled={busy} aria-label={`Close ${label.toLowerCase()}`} className="inline-flex size-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:opacity-50">
            <X className="size-4" aria-hidden />
          </button>
        </header>
        {!task && !error ? <p className="mt-4 text-sm text-zinc-400">Loading reminder task…</p> : null}
        {task && mode === 'edit' ? (
          <form className="mt-4 space-y-3" onSubmit={(event) => void submitEdit(event)}>
            <label className="block text-xs text-zinc-300">Title
              <input value={title} maxLength={500} disabled={busy} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full rounded-md border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-zinc-100 focus:border-[#7EB3FF]/60 focus:outline-none focus:ring-1 focus:ring-[#7EB3FF]/40" />
            </label>
            <label className="block text-xs text-zinc-300">Importance
              <select value={importance} disabled={busy} onChange={(event) => setImportance(event.target.value as ReminderTaskDetail['importance'])} className="mt-1 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 [color-scheme:dark] focus:border-[#7EB3FF]/60 focus:outline-none focus:ring-1 focus:ring-[#7EB3FF]/40">
                <option value="low" className="bg-zinc-950 text-zinc-100">Low</option><option value="normal" className="bg-zinc-950 text-zinc-100">Normal</option><option value="high" className="bg-zinc-950 text-zinc-100">High</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300"><input type="checkbox" checked={hasDue} disabled={busy} onChange={(event) => setHasDue(event.target.checked)} /> Include due date</label>
            {hasDue ? <label className="block text-xs text-zinc-300">Due date and time
              <input type="datetime-local" value={dueValue} disabled={busy} onChange={(event) => setDueValue(event.target.value)} className="mt-1 w-full rounded-md border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-zinc-100 focus:border-[#7EB3FF]/60 focus:outline-none" />
              <span className="mt-1 block font-mono text-[10px] uppercase tracking-wide text-zinc-500">Timezone: {timeZone}</span>
            </label> : null}
            {error ? <p role="alert" className="text-xs text-red-300">{error}</p> : null}
            <button type="submit" disabled={busy || !changes} className="rounded border border-[#7EB3FF]/30 bg-[#7EB3FF]/10 px-3 py-1.5 text-xs text-[#9AC2FF] disabled:opacity-50">Save changes</button>
          </form>
        ) : null}
        {task && mode === 'delete' ? (
          <div className="mt-4 space-y-4">
            <p className="text-sm leading-relaxed text-zinc-300">Delete <span className="font-medium text-zinc-100">{task.title}</span> from Microsoft To Do? APEX cannot undo this action.</p>
            {error ? <p role="alert" className="text-xs text-red-300">{error}</p> : null}
            <div className="flex gap-2"><button type="button" disabled={busy} onClick={onClose} className="rounded border border-white/10 px-3 py-1.5 text-xs text-zinc-300 disabled:opacity-50">Cancel</button><button type="button" disabled={busy} onClick={() => void submitDelete()} className="rounded border border-red-400/30 bg-red-400/10 px-3 py-1.5 text-xs text-red-200 disabled:opacity-50">Delete task</button></div>
          </div>
        ) : null}
        {!task && error ? <p role="alert" className="mt-4 text-xs text-red-300">{error}</p> : null}
      </div>
    </div>,
    document.body,
  )
}
