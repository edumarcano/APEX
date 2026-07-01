import {
  useCallback,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

import {
  CloudProfileSelector,
  type CloudProfile,
} from './CloudProfileSelector'

interface AskApexBarProps {
  activeProfile: CloudProfile
  onProfileChange: (profile: CloudProfile) => void
  onSubmit: (query: string, profile: CloudProfile) => void
  isSubmitting: boolean
  disabled?: boolean
}

export function AskApexBar({
  activeProfile,
  onProfileChange,
  onSubmit,
  isSubmitting,
  disabled = false,
}: AskApexBarProps): ReactElement {
  const [query, setQuery] = useState('')
  const isInputDisabled = disabled || isSubmitting

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>): void => {
      event.preventDefault()

      const trimmed = query.trim()
      if (!trimmed || isSubmitting || disabled) {
        return
      }

      onSubmit(trimmed, activeProfile)
      setQuery('')
    },
    [activeProfile, disabled, isSubmitting, onSubmit, query],
  )

  const handleInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>): void => {
      if (event.key !== 'Escape') {
        return
      }

      setQuery('')
      event.currentTarget.blur()
    },
    [],
  )

  return (
    <form
      onSubmit={handleSubmit}
      className={[
        'w-80 sm:w-[380px] xl:w-[460px] rounded-xl border bg-zinc-950/40 backdrop-blur-md',
        'border-white/10 transition-all duration-300',
        'focus-within:border-[#0F4DB8]/60 focus-within:shadow-[0_0_12px_rgba(15,77,184,0.2)]',
        disabled ? 'opacity-50' : '',
      ].join(' ')}
      aria-label="Ask APEX"
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <span
          className="shrink-0 font-mono text-sm font-semibold text-[#0F4DB8]"
          aria-hidden
        >
          &gt;_
        </span>

        <input
          type="text"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
          }}
          onKeyDown={handleInputKeyDown}
          placeholder="Ask APEX about this briefing or live telemetry..."
          disabled={isInputDisabled}
          className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none focus:ring-0"
          aria-label="Ask APEX query"
          autoComplete="off"
          spellCheck={false}
        />

        <CloudProfileSelector
          activeProfile={activeProfile}
          onChange={onProfileChange}
          disabled={isInputDisabled}
        />
      </div>
    </form>
  )
}
