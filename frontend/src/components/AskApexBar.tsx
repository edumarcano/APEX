import {
  useCallback,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

import type { AgentProfileStatus, AssistantProfile } from '../types/telemetry'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'

import { CloudProfileSelector } from './CloudProfileSelector'

interface AskApexBarProps {
  activeProfile: AssistantProfile
  onProfileChange: (profile: AssistantProfile) => void
  onSubmit: (query: string, profile: AssistantProfile) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  onSelectChip?: (query: string) => void
  isSubmitting: boolean
  disabled?: boolean
  integrated?: boolean
}

export function AskApexBar({
  activeProfile,
  onProfileChange,
  onSubmit,
  profilesStatus,
  profilesStatusHydrated,
  onSelectChip,
  isSubmitting,
  disabled = false,
  integrated = false,
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

  const chipClassName = [
    'px-2 py-0.5 rounded-full border border-white/5 bg-white/5',
    'hover:border-[#0F4DB8]/40 hover:bg-[#0F4DB8]/10',
    'text-[10px] text-zinc-400 hover:text-white transition-colors',
    'cursor-pointer shrink-0 font-mono uppercase tracking-wider',
    isInputDisabled ? 'pointer-events-none opacity-50' : '',
  ].join(' ')

  const wrapperClassName = integrated
    ? 'w-full max-w-full'
    : 'w-80 sm:w-[380px] xl:w-[460px]'

  const formClassName = integrated
    ? [
        'hud-command-surface w-full rounded-lg bg-zinc-950/20 shadow-none backdrop-blur-none',
        'transition-all duration-300',
        disabled ? 'opacity-50' : '',
      ].join(' ')
    : [
        'w-full rounded-xl border bg-zinc-950/40 backdrop-blur-md',
        'border-white/10 transition-all duration-300',
        'focus-within:border-[#0F4DB8]/60 focus-within:shadow-[0_0_12px_rgba(15,77,184,0.2)]',
        disabled ? 'opacity-50' : '',
      ].join(' ')

  return (
    <div className={wrapperClassName}>
      {!integrated && query.length === 0 ? (
        <div className="flex items-center gap-2 overflow-x-auto pb-1.5 scrollbar-none w-full max-w-full">
          {OPERATION_PROMPT_CHIPS.map((chip) => (
            <button
              key={chip.label}
              type="button"
              onClick={() => {
                onSelectChip?.(chip.query)
              }}
              disabled={isInputDisabled}
              className={chipClassName}
            >
              {chip.label}
            </button>
          ))}
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        className={formClassName}
        aria-label="Ask APEX"
      >
        <div className={`flex items-center gap-3 ${integrated ? 'px-3 py-2' : 'px-4 py-3'}`}>
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
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            disabled={isInputDisabled}
          />
        </div>
      </form>
    </div>
  )
}
