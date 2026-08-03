import { Plus, Send } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

type ReminderQuickAddProps = {
  onSave: (text: string) => Promise<void>
}

type PopoverPosition = {
  left: number
  top: number
  opensUpward: boolean
}

const POPOVER_WIDTH = 320
const VIEWPORT_GUTTER = 8
const POPOVER_OFFSET = 6
const POPOVER_ESTIMATED_HEIGHT = 164

function resolvePopoverPosition(trigger: HTMLButtonElement): PopoverPosition {
  const rect = trigger.getBoundingClientRect()
  const viewportWidth = window.innerWidth || 1024
  const viewportHeight = window.innerHeight || 768
  const width = Math.min(POPOVER_WIDTH, viewportWidth - VIEWPORT_GUTTER * 2)
  const left = Math.min(
    Math.max(VIEWPORT_GUTTER, rect.right - width),
    Math.max(VIEWPORT_GUTTER, viewportWidth - width - VIEWPORT_GUTTER),
  )
  const opensUpward = rect.bottom + POPOVER_ESTIMATED_HEIGHT > viewportHeight

  return {
    left,
    top: opensUpward ? rect.top - POPOVER_OFFSET : rect.bottom + POPOVER_OFFSET,
    opensUpward,
  }
}

export function ReminderQuickAdd({ onSave }: ReminderQuickAddProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false)
  const [text, setText] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [position, setPosition] = useState<PopoverPosition | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const closePopover = useCallback((): void => {
    if (isSaving) return
    setIsOpen(false)
    setError(null)
    setText('')
    triggerRef.current?.focus()
  }, [isSaving])

  const openPopover = useCallback((): void => {
    const trigger = triggerRef.current
    if (!trigger) return
    setPosition(resolvePopoverPosition(trigger))
    setError(null)
    setText('')
    setIsOpen(true)
  }, [])

  useEffect(() => {
    if (!isOpen) return

    const updatePosition = (): void => {
      if (triggerRef.current) {
        setPosition(resolvePopoverPosition(triggerRef.current))
      }
    }
    const handlePointerDown = (event: PointerEvent): void => {
      const target = event.target as Node
      if (!triggerRef.current?.contains(target) && !popoverRef.current?.contains(target)) {
        closePopover()
      }
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closePopover()
      }
    }

    inputRef.current?.focus()
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [closePopover, isOpen])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    const trimmedText = text.trim()
    if (!trimmedText || isSaving) return

    setIsSaving(true)
    setError(null)
    try {
      await onSave(trimmedText)
      setIsSaving(false)
      setIsOpen(false)
      setText('')
      triggerRef.current?.focus()
    } catch {
      setIsSaving(false)
      setError('Could not save reminder. Try again.')
      inputRef.current?.focus()
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          if (isOpen) {
            closePopover()
          } else {
            openPopover()
          }
        }}
        aria-label="Add reminder"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[color:var(--hud-muted-text)] transition-colors hover:border-[#7EB3FF]/40 hover:bg-[#7EB3FF]/10 hover:text-[color:var(--hud-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
      >
        <Plus className="size-4" strokeWidth={2} aria-hidden />
      </button>
      {isOpen && position
        ? createPortal(
            <div
              ref={popoverRef}
              role="dialog"
              aria-label="Add reminder"
              className="fixed z-[var(--z-overlay)] w-[min(20rem,calc(100vw-1rem))] rounded-xl border border-white/15 bg-zinc-950/95 p-3 shadow-2xl backdrop-blur-md"
              style={{
                left: position.left,
                top: position.top,
                transform: position.opensUpward ? 'translateY(-100%)' : undefined,
              }}
            >
              <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--hud-text)]">
                Add reminder
              </p>
              <form className="mt-2" onSubmit={handleSubmit}>
                <div className="flex items-center gap-2">
                  <label className="sr-only" htmlFor="reminder-quick-add-input">
                    Reminder text
                  </label>
                  <input
                    ref={inputRef}
                    id="reminder-quick-add-input"
                    type="text"
                    value={text}
                    maxLength={4096}
                    onChange={(event) => setText(event.target.value)}
                    placeholder="Reminder text…"
                    disabled={isSaving}
                    className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-[#7EB3FF]/60 focus:outline-none focus:ring-1 focus:ring-[#7EB3FF]/40 disabled:opacity-60"
                  />
                  <button
                    type="submit"
                    disabled={!text.trim() || isSaving}
                    aria-label="Save reminder"
                    className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-[#7EB3FF]/30 bg-[#7EB3FF]/10 text-[#9AC2FF] transition-colors hover:border-[#7EB3FF]/60 hover:bg-[#7EB3FF]/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Send className="size-4" strokeWidth={2} aria-hidden />
                  </button>
                </div>
                {error ? (
                  <p className="mt-2 text-xs text-[#F87171]" role="alert">
                    {error}
                  </p>
                ) : (
                  <p className="mt-2 text-[11px] text-zinc-500">Saved locally for the next briefing.</p>
                )}
              </form>
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
