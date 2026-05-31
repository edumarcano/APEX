import { Terminal } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from 'react'

const REMINDERS_ENDPOINT = 'http://127.0.0.1:8000/api/v1/reminders'
const SUCCESS_PULSE_MS = 500

type ReminderTerminalProps = {
  refreshReminders: () => Promise<void>
}

export function ReminderTerminal({
  refreshReminders,
}: ReminderTerminalProps): ReactElement {
  const inputRef = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [successPulse, setSuccessPulse] = useState(false)

  useEffect(() => {
    const handleGlobalSlash = (event: KeyboardEvent): void => {
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
      inputRef.current?.focus()
    }

    window.addEventListener('keydown', handleGlobalSlash)
    return () => {
      window.removeEventListener('keydown', handleGlobalSlash)
    }
  }, [])

  const triggerSuccessPulse = useCallback((): void => {
    setSuccessPulse(true)
    window.setTimeout(() => {
      setSuccessPulse(false)
    }, SUCCESS_PULSE_MS)
  }, [])

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

        setValue('')
        triggerSuccessPulse()
        await refreshReminders()
      } catch {
        // Submission errors leave the input intact for retry.
      } finally {
        setIsSubmitting(false)
      }
    },
    [isSubmitting, refreshReminders, triggerSuccessPulse, value],
  )

  const containerClassName = [
    'bg-zinc-950/40 backdrop-blur-md border rounded-xl shadow-2xl transition-all duration-300',
    successPulse
      ? 'border-emerald-500/80 shadow-[0_0_24px_rgba(16,185,129,0.35)]'
      : 'border-white/10 focus-within:border-emerald-500/50',
  ].join(' ')

  return (
    <div className="fixed bottom-6 left-1/2 z-50 w-full max-w-xl -translate-x-1/2 px-4">
      <form
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
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
            placeholder="Add a reminder…  (press / to focus)"
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
