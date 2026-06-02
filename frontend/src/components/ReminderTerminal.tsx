import { Terminal } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

const REMINDERS_ENDPOINT = 'http://127.0.0.1:8000/api/v1/reminders'
const SUCCESS_PULSE_MS = 500
const COLLAPSE_SETTLE_MS = 2000
const COLLAPSE_AFTER_SUCCESS_MS = SUCCESS_PULSE_MS + COLLAPSE_SETTLE_MS

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

type ReminderTerminalProps = {
  refreshReminders: () => Promise<void>
  onReminderSaved?: () => void
}

export function ReminderTerminal({
  refreshReminders,
  onReminderSaved,
}: ReminderTerminalProps): ReactElement {
  const inputRef = useRef<HTMLInputElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [dockVisible, setDockVisible] = useState(false)
  const [value, setValue] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [successPulse, setSuccessPulse] = useState(false)

  const openTerminal = useCallback((): void => {
    setIsOpen(true)
  }, [])

  useEffect(() => {
    if (!isOpen) {
      setDockVisible(false)
      return
    }

    const frame = window.requestAnimationFrame(() => {
      setDockVisible(true)
    })
    inputRef.current?.focus()

    return () => {
      window.cancelAnimationFrame(frame)
    }
  }, [isOpen])

  useEffect(() => {
    const handleGlobalSlash = (event: globalThis.KeyboardEvent): void => {
      if (event.key !== '/') {
        return
      }

      const target = event.target
      if (!(target instanceof HTMLElement)) {
        return
      }

      const tagName = target.tagName
      if (
        tagName === 'INPUT' ||
        tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return
      }

      event.preventDefault()
      openTerminal()
    }

    window.addEventListener('keydown', handleGlobalSlash)
    return () => {
      window.removeEventListener('keydown', handleGlobalSlash)
    }
  }, [openTerminal])

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>): Promise<void> => {
      event.preventDefault()

      const trimmed = value.trim()
      if (!trimmed || isSubmitting) {
        return
      }

      setIsSubmitting(true)

      try {
        const response = await fetch(REMINDERS_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: trimmed }),
        })

        if (!response.ok) {
          return
        }

        onReminderSaved?.()
        setValue('')
        setSuccessPulse(true)
        await refreshReminders()
        await delay(COLLAPSE_AFTER_SUCCESS_MS)
        setSuccessPulse(false)
        inputRef.current?.blur()
        setIsOpen(false)
      } catch {
        // Submission errors leave the input intact for retry.
      } finally {
        setIsSubmitting(false)
      }
    },
    [isSubmitting, onReminderSaved, refreshReminders, value],
  )

  const handleInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>): void => {
      if (event.key !== 'Escape') {
        return
      }

      setValue('')
      event.currentTarget.blur()
      setIsOpen(false)
    },
    [],
  )

  const handleFormBlur = useCallback((event: FocusEvent<HTMLFormElement>): void => {
    const next = event.relatedTarget
    if (next instanceof Node && event.currentTarget.contains(next)) {
      return
    }

    window.setTimeout(() => {
      const form = formRef.current
      if (form && !form.contains(document.activeElement)) {
        setIsOpen(false)
      }
    }, 0)
  }, [])

  const containerClassName = [
    'bg-zinc-950/40 backdrop-blur-md border rounded-xl shadow-2xl transition-all duration-300',
    successPulse
      ? 'border-amber-500/80 shadow-[0_0_24px_rgba(234,179,8,0.35)]'
      : 'border-white/10 focus-within:border-emerald-500/50',
  ].join(' ')

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={openTerminal}
        className="mt-3 flex w-full items-center justify-center gap-2 py-2.5 text-sm text-[color:var(--hud-muted-text)] transition-colors hover:text-[color:var(--hud-text)]"
        aria-label="Add a reminder. Press slash to focus."
      >
        <Terminal
          className="size-4 shrink-0 text-emerald-500/50"
          strokeWidth={1.75}
          aria-hidden
        />
        <span>Add a reminder… (press / to focus)</span>
      </button>
    )
  }

  return (
    <div
      className={[
        'fixed bottom-6 left-1/2 z-50 w-full max-w-xl px-4 transition-all duration-200 ease-out',
        dockVisible
          ? 'opacity-100 -translate-x-1/2 translate-y-0'
          : 'opacity-0 -translate-x-1/2 translate-y-4',
      ].join(' ')}
    >
      <form
        ref={formRef}
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
        onBlur={handleFormBlur}
        className={containerClassName}
        aria-label="Reminder terminal"
      >
        <div className="flex items-center gap-3 px-4 py-3">
          <Terminal
            className="size-4 shrink-0 text-emerald-500/70"
            strokeWidth={1.75}
            aria-hidden
          />
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(event) => {
              setValue(event.target.value)
            }}
            onKeyDown={handleInputKeyDown}
            placeholder="Add a reminder…"
            disabled={isSubmitting}
            className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none"
            aria-label="Reminder text"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </form>
    </div>
  )
}
