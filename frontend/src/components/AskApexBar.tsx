import {
  useCallback,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'
import { Send } from 'lucide-react'

import type {
  AgentProfileStatus,
  AssistantProfile,
  LocalCommandStatus,
  LocalToolScope,
} from '../types/telemetry'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'
import { profileShortName } from '../lib/profileDisplay'

import { ProfileMark } from './ProfileMark'

interface AskApexBarProps {
  activeProfile: AssistantProfile
  onSubmit: (query: string, profile: AssistantProfile, toolScope?: LocalToolScope | null) => void
  profilesStatus: AgentProfileStatus[]
  commands?: LocalCommandStatus[]
  armedToolScope?: LocalToolScope | null
  onArmedToolScopeChange?: (scope: LocalToolScope | null) => void
  onSelectChip?: (query: string) => void
  isSubmitting: boolean
  disabled?: boolean
  integrated?: boolean
}

export function AskApexBar({
  activeProfile,
  onSubmit,
  profilesStatus,
  commands = [],
  armedToolScope = null,
  onArmedToolScopeChange,
  onSelectChip,
  isSubmitting,
  disabled = false,
  integrated = false,
}: AskApexBarProps): ReactElement {
  const [query, setQuery] = useState('')
  const isInputDisabled = disabled || isSubmitting
  const isLocalProfile = profilesStatus.some((profile) => profile.key === activeProfile && profile.provider === 'ollama')
  const activeProfileName = profileShortName(
    profilesStatus.find((profile) => profile.key === activeProfile)?.display_name ?? activeProfile,
  )

  const handleSubmit = useCallback((event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || isSubmitting || disabled) return

    const [possibleCommand, ...remaining] = trimmed.split(/\s+/)
    const command = commands.find((item) => item.command.toLowerCase() === possibleCommand.toLowerCase())
    if (command && remaining.length === 0) {
      if (command.available) onArmedToolScopeChange?.(command.key)
      setQuery('')
      return
    }
    if (command && !command.available) return

    onSubmit(command ? remaining.join(' ') : trimmed, activeProfile, command?.key ?? armedToolScope)
    onArmedToolScopeChange?.(null)
    setQuery('')
  }, [activeProfile, armedToolScope, commands, disabled, isSubmitting, onArmedToolScopeChange, onSubmit, query])

  const handleInputKeyDown = useCallback((event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== 'Escape') return
    setQuery('')
    event.currentTarget.blur()
  }, [])

  const chipClassName = [
    'px-2 py-0.5 rounded-full border border-white/5 bg-white/5',
    'hover:border-[#0F4DB8]/40 hover:bg-[#0F4DB8]/10',
    'text-[10px] text-zinc-400 hover:text-white transition-colors',
    'cursor-pointer shrink-0 font-mono uppercase tracking-wider',
    isInputDisabled ? 'pointer-events-none opacity-50' : '',
  ].join(' ')
  const wrapperClassName = integrated ? 'w-full max-w-full' : 'w-80 sm:w-[380px] xl:w-[460px]'
  const formClassName = integrated
    ? ['hud-command-surface w-full rounded-lg bg-zinc-950/20 shadow-none backdrop-blur-none', 'transition-all duration-300', disabled ? 'opacity-50' : ''].join(' ')
    : ['w-full rounded-xl border bg-zinc-950/40 backdrop-blur-md', 'border-white/10 transition-all duration-300', 'focus-within:border-[#0F4DB8]/60 focus-within:shadow-[0_0_12px_rgba(15,77,184,0.2)]', disabled ? 'opacity-50' : ''].join(' ')

  return <div className={wrapperClassName}>
    {!integrated && query.length === 0 ? <div className="flex w-full max-w-full gap-2 overflow-x-auto pb-1.5 scrollbar-none">{OPERATION_PROMPT_CHIPS.map((chip) => <button key={chip.label} type="button" onClick={() => onSelectChip?.(chip.query)} disabled={isInputDisabled} className={chipClassName}>{chip.label}</button>)}</div> : null}
    <form onSubmit={handleSubmit} className={formClassName} aria-label="Ask APEX">
      <div className={`flex items-center gap-3 ${integrated ? 'px-3 py-2' : 'px-4 py-3'}`}>
        <span className="shrink-0 font-mono text-sm font-semibold text-[#0F4DB8]" aria-hidden>&gt;_</span>
        <input type="text" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Ask APEX about this briefing or live telemetry..." disabled={isInputDisabled} className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none focus:ring-0" aria-label="Ask APEX query" autoComplete="off" spellCheck={false} />
        {isLocalProfile && armedToolScope ? <span className="hidden shrink-0 rounded-md border border-orange-400/25 bg-orange-950/20 px-2 py-1 font-mono text-[10px] text-orange-200 sm:inline">Tool scope: /{armedToolScope}</span> : null}
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[10px] text-zinc-400" aria-label={`Active profile ${activeProfileName}`}><ProfileMark profile={activeProfile} /><span className="hidden sm:inline">{activeProfileName}</span></span>
        <button type="submit" disabled={isInputDisabled || query.trim().length === 0} className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#7E22CE]/45 bg-[#7E22CE]/15 text-[#E9D5FF] transition-colors hover:border-[#C084FC] hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-40" aria-label="Send query"><Send className="size-3.5" aria-hidden /></button>
      </div>
    </form>
  </div>
}
