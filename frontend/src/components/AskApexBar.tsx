import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'
import { CircleAlert, Loader2, Send } from 'lucide-react'

import type {
  AgentStatus,
  AgentKey,
  LocalCommandStatus,
  LocalToolScope,
} from '../types/telemetry'
import { agentShortName } from '../lib/agentDisplay'

import { AgentMark } from './AgentMark'

function CortexErrorFeedback({ error }: { error: string }): ReactElement | null {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setVisible(false), 4_000)
    return () => window.clearTimeout(timeoutId)
  }, [])

  if (!visible) return null
  return <span className="cortex-error-feedback pointer-events-none absolute inset-0 flex items-center justify-end rounded-xl border border-red-400/70 pr-12 text-red-300" role="status" aria-label={`Last query failed: ${error}`}><CircleAlert className="size-4" aria-hidden /></span>
}

interface AskApexBarProps {
  activeAgent: AgentKey
  onSubmit: (query: string, agent: AgentKey, toolScope?: LocalToolScope | null) => void
  agentsStatus: AgentStatus[]
  commands?: LocalCommandStatus[]
  armedToolScope?: LocalToolScope | null
  onArmedToolScopeChange?: (scope: LocalToolScope | null) => void
  isSubmitting: boolean
  disabled?: boolean
  presentation: 'cortex' | 'home'
  error?: string | null
}

export function AskApexBar({
  activeAgent,
  onSubmit,
  agentsStatus,
  commands = [],
  armedToolScope = null,
  onArmedToolScopeChange,
  isSubmitting,
  disabled = false,
  presentation,
  error = null,
}: AskApexBarProps): ReactElement {
  const [query, setQuery] = useState('')
  const isInputDisabled = disabled || isSubmitting
  const isLocalAgent = agentsStatus.some((agent) => agent.key === activeAgent && agent.runtime === 'local')
  const activeAgentName = agentShortName(
    agentsStatus.find((agent) => agent.key === activeAgent)?.display_name ?? activeAgent,
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

    onSubmit(command ? remaining.join(' ') : trimmed, activeAgent, command?.key ?? armedToolScope)
    onArmedToolScopeChange?.(null)
    setQuery('')
  }, [activeAgent, armedToolScope, commands, disabled, isSubmitting, onArmedToolScopeChange, onSubmit, query])

  const handleInputKeyDown = useCallback((event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== 'Escape') return
    setQuery('')
    event.currentTarget.blur()
  }, [])

  const home = presentation === 'home'
  const cortex = presentation === 'cortex'
  const wrapperClassName = 'w-full max-w-full'
  const cortexStateClassName = isSubmitting
    ? 'cortex-ask-apex-bar--active border-[#A855F7]/70'
    : cortex && error
      ? 'cortex-ask-apex-bar--error'
      : 'border-white/15'
  const formClassName = cortex
    ? [
      'cortex-ask-apex-bar relative hud-command-surface w-full min-h-12 rounded-xl border bg-zinc-950/65 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-md',
      'transition-[border-color,box-shadow,background-color] duration-300 focus-within:border-[#0F4DB8]/70 focus-within:shadow-[0_0_16px_rgba(15,77,184,0.24)] sm:min-h-14',
      cortexStateClassName,
      disabled ? 'opacity-50' : '',
    ].join(' ')
    : ['w-full bg-transparent', 'transition-colors duration-300 focus-within:bg-white/[0.02]', disabled ? 'opacity-50' : ''].join(' ')

  return <div className={wrapperClassName}>
    <form onSubmit={handleSubmit} className={formClassName} aria-label="Ask APEX" aria-busy={isSubmitting}>
      <div className={`flex items-center gap-3 ${cortex ? 'min-h-12 px-3 py-2 sm:min-h-14 sm:px-4' : 'min-h-10 px-2 py-1'}`}>
        <span className="shrink-0 font-mono text-sm font-semibold text-[#0F4DB8]" aria-hidden>&gt;_</span>
        <input type="text" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Ask APEX" disabled={isInputDisabled} className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none focus:ring-0" aria-label="Ask APEX query" autoComplete="off" spellCheck={false} />
        {isLocalAgent && armedToolScope ? <span className="hidden shrink-0 rounded-md border border-orange-400/25 bg-orange-950/20 px-2 py-1 font-mono text-[10px] text-orange-200 sm:inline">Tool scope: /{armedToolScope}</span> : null}
        {!home ? <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[10px] text-zinc-400" aria-label={`Active agent ${activeAgentName}`}><AgentMark agent={activeAgent} /><span className="hidden sm:inline">{activeAgentName}</span></span> : null}
        <button type="submit" disabled={isInputDisabled || query.trim().length === 0} className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#7E22CE]/45 bg-[#7E22CE]/15 text-[#E9D5FF] transition-colors hover:border-[#C084FC] hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-40" aria-label={isSubmitting ? 'Sending query' : 'Send query'}>{isSubmitting ? <Loader2 className="cortex-query-spinner size-3.5" aria-hidden /> : <Send className="size-3.5" aria-hidden />}</button>
      </div>
      {cortex && error ? <CortexErrorFeedback key={error} error={error} /> : null}
    </form>
  </div>
}
