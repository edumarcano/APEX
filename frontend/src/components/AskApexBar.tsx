import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

import type {
  AgentProfileStatus,
  AssistantProfile,
  LocalCommandStatus,
  LocalContextUsage,
  LocalToolScope,
} from '../types/telemetry'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'
import { API_ENDPOINTS } from '../lib/api'

import { CloudProfileSelector } from './CloudProfileSelector'

interface AskApexBarProps {
  activeProfile: AssistantProfile
  onProfileChange: (profile: AssistantProfile) => void
  onSubmit: (
    query: string,
    profile: AssistantProfile,
    toolScope?: LocalToolScope | null,
  ) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  onSelectChip?: (query: string) => void
  isSubmitting: boolean
  disabled?: boolean
  integrated?: boolean
  showCommands?: boolean
  contextUsage?: LocalContextUsage | null
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
  showCommands = false,
  contextUsage = null,
}: AskApexBarProps): ReactElement {
  const [query, setQuery] = useState('')
  const [commands, setCommands] = useState<LocalCommandStatus[]>([])
  const [commandsOpen, setCommandsOpen] = useState(false)
  const [activeScope, setActiveScope] = useState<LocalToolScope | null>(null)
  const isInputDisabled = disabled || isSubmitting
  const isLocalProfile = profilesStatus.some(
    (profile) => profile.key === activeProfile && profile.provider === 'ollama',
  )
  const showLocalCommands = showCommands && isLocalProfile
  const slashPrefix =
    query.startsWith('/') && !query.includes(' ') ? query.toLowerCase() : null
  const matchingCommands = slashPrefix
    ? commands.filter((command) => command.command.startsWith(slashPrefix))
    : []

  useEffect(() => {
    if (!showLocalCommands) {
      return
    }
    let cancelled = false
    void fetch(API_ENDPOINTS.agentCommands)
      .then(async (response) => {
        if (!response.ok) {
          return []
        }
        return (await response.json()) as LocalCommandStatus[]
      })
      .then((items) => {
        if (!cancelled && Array.isArray(items)) {
          setCommands(items)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCommands([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [showLocalCommands])

  const selectCommand = useCallback((command: LocalCommandStatus): void => {
    if (!command.available) {
      return
    }
    setActiveScope(command.key)
    setQuery('')
    setCommandsOpen(false)
  }, [])

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>): void => {
      event.preventDefault()

      const trimmed = query.trim()
      if (!trimmed || isSubmitting || disabled) {
        return
      }

      const [possibleCommand, ...remaining] = trimmed.split(/\s+/)
      const command = commands.find(
        (item) => item.command.toLowerCase() === possibleCommand.toLowerCase(),
      )
      if (command && remaining.length === 0) {
        selectCommand(command)
        return
      }
      if (command && !command.available) {
        return
      }
      const submittedQuery = command ? remaining.join(' ') : trimmed
      onSubmit(submittedQuery, activeProfile, command?.key ?? activeScope)
      setActiveScope(null)
      setQuery('')
    },
    [
      activeProfile,
      activeScope,
      commands,
      disabled,
      isSubmitting,
      onSubmit,
      query,
      selectCommand,
    ],
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
      {showLocalCommands ? (
        <div className="relative mb-2 font-mono text-[10px]">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setCommandsOpen((open) => !open)}
              className="rounded-md border border-white/10 bg-zinc-950/70 px-2 py-1 uppercase tracking-wider text-zinc-300 hover:border-[#0F4DB8]/50"
              aria-expanded={commandsOpen}
            >
              Commands
            </button>
            <span className="text-zinc-500">
              {activeScope ? `/${activeScope} armed · one shot` : 'No tools'}
            </span>
            {contextUsage ? (
              <span
                className={`ml-auto ${
                  contextUsage.estimated_prompt_tokens / contextUsage.context_window >= 0.8
                    ? 'text-amber-400'
                    : 'text-zinc-500'
                }`}
                title={`${contextUsage.history_messages_dropped} history messages trimmed`}
              >
                {contextUsage.peak_prompt_tokens ??
                  contextUsage.estimated_prompt_tokens}
                /{contextUsage.context_window} tokens
              </span>
            ) : null}
          </div>
          {commandsOpen || matchingCommands.length > 0 ? (
            <div className="absolute bottom-full z-30 mb-2 grid w-full gap-1 rounded-lg border border-white/10 bg-zinc-950/95 p-2 shadow-xl">
              {(matchingCommands.length > 0 ? matchingCommands : commands).map(
                (command) => (
                  <button
                    key={command.key}
                    type="button"
                    onClick={() => selectCommand(command)}
                    disabled={!command.available}
                    title={command.unavailable_reason ?? undefined}
                    className="flex items-center gap-2 rounded px-2 py-1.5 text-left text-zinc-300 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className="w-20 text-[#4B82E3]">{command.command}</span>
                    <span className="min-w-0 flex-1 truncate">
                      {command.description}
                    </span>
                    <span className="shrink-0 text-zinc-600">
                      ~{command.estimated_schema_tokens}
                    </span>
                  </button>
                ),
              )}
            </div>
          ) : null}
        </div>
      ) : null}
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
            onChange={(profile) => {
              setActiveScope(null)
              setCommandsOpen(false)
              onProfileChange(profile)
            }}
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            disabled={isInputDisabled}
          />
        </div>
      </form>
    </div>
  )
}
