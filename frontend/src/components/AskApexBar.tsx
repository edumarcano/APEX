import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'
import { CircleAlert, Loader2, Send } from 'lucide-react'

import type {
  AgentStatus,
  AgentKey,
  ToolCatalog,
  ToolPreflightEstimate,
} from '../types/telemetry'
import { agentShortName } from '../lib/agentDisplay'

import { AgentMark } from './AgentMark'
import { ToolsSelector } from './ToolsSelector'

function CortexQueryRim(): ReactElement {
  const accentRgb = '168, 85, 247'
  const dualSweep = `conic-gradient(from 0deg,
    rgba(${accentRgb}, 0) 0deg,
    rgba(${accentRgb}, 0.15) 15deg,
    rgba(${accentRgb}, 0.95) 45deg,
    rgba(${accentRgb}, 0.15) 75deg,
    rgba(${accentRgb}, 0) 90deg,
    rgba(${accentRgb}, 0) 180deg,
    rgba(${accentRgb}, 0.15) 195deg,
    rgba(${accentRgb}, 0.95) 225deg,
    rgba(${accentRgb}, 0.15) 255deg,
    rgba(${accentRgb}, 0) 270deg,
    rgba(${accentRgb}, 0) 360deg)`
  const ringMask = {
    WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    WebkitMaskComposite: 'xor',
    mask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    maskComposite: 'exclude',
  } as const

  return <div className="pointer-events-none absolute inset-0 z-[25] overflow-hidden rounded-xl" aria-hidden data-slot="cortex-query-rim">
    <div className="absolute inset-0 rounded-xl" style={{ boxShadow: `inset 0 0 0 1px rgba(${accentRgb}, 0.55), 0 0 18px rgba(${accentRgb}, 0.28)` }} />
    {[5, 2].map((padding) => <div key={padding} className="absolute inset-0 overflow-hidden rounded-xl" style={{ padding: `${padding}px`, ...ringMask }}>
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
        <div className="cortex-query-rim__sweep" style={{ width: '200vmax', height: '200vmax', background: dualSweep, opacity: padding === 5 ? 0.55 : 1 }} />
      </div>
    </div>)}
  </div>
}

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
  onSubmit: (
    query: string,
    agent: AgentKey,
    selectedToolNames: string[],
    toolProfileId: string | null,
  ) => Promise<boolean>
  agentsStatus: AgentStatus[]
  catalog: ToolCatalog | null
  selectedToolNames: string[]
  activeToolProfileId: string | null
  onToolSelectionChange?: (names: string[]) => void
  onToolProfileChange?: (profileId: string) => void
  toolPreflight?: ToolPreflightEstimate | null
  toolPreflightLoading?: boolean
  toolCatalogError?: string | null
  toolPreflightError?: string | null
  toolProfileFeedback?: string | null
  toolProfileError?: string | null
  onSaveToolProfile?: (name: string) => void
  onDuplicateToolProfile?: (profileId: string, name: string) => void
  onRenameToolProfile?: (profileId: string, name: string) => void
  onDeleteToolProfile?: (profileId: string) => void
  onRestoreToolProfile?: (profileId: string) => void
  onSetDefaultToolProfile?: (profileId: string) => void
  isSubmitting: boolean
  submissionPending?: boolean
  disabled?: boolean
  selectionReady?: boolean
  draftPrompt?: string
  onDraftChange?: (value: string) => void
  presentation: 'cortex' | 'home'
  error?: string | null
}

export function AskApexBar({
  activeAgent,
  onSubmit,
  agentsStatus,
  catalog,
  selectedToolNames,
  activeToolProfileId,
  onToolSelectionChange,
  onToolProfileChange,
  toolPreflight = null,
  toolPreflightLoading = false,
  toolCatalogError = null,
  toolPreflightError = null,
  toolProfileFeedback = null,
  toolProfileError = null,
  onSaveToolProfile,
  onDuplicateToolProfile,
  onRenameToolProfile,
  onDeleteToolProfile,
  onRestoreToolProfile,
  onSetDefaultToolProfile,
  isSubmitting,
  submissionPending = false,
  disabled = false,
  selectionReady = true,
  draftPrompt,
  onDraftChange,
  presentation,
  error = null,
}: AskApexBarProps): ReactElement {
  const [localQuery, setLocalQuery] = useState('')
  const query = draftPrompt ?? localQuery
  const draftRef = useRef(query)
  useEffect(() => {
    draftRef.current = query
  }, [query])
  const editorDisabled = disabled || isSubmitting || !selectionReady
  const submitDisabled =
    editorDisabled ||
    submissionPending ||
    query.trim().length === 0 ||
    toolPreflight?.can_proceed === false
  const activeAgentName = agentShortName(
    agentsStatus.find((agent) => agent.key === activeAgent)?.display_name ?? activeAgent,
  )
  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || submitDisabled) return
    const submittedDraft = query
    try {
      const accepted = await onSubmit(trimmed, activeAgent, selectedToolNames, activeToolProfileId)
      if (!accepted || draftRef.current !== submittedDraft) return
    } catch {
      // A rejected submission leaves the draft available for retry.
      return
    }
    setLocalQuery('')
    draftRef.current = ''
    onDraftChange?.('')
  }, [activeAgent, activeToolProfileId, onDraftChange, onSubmit, query, selectedToolNames, submitDisabled])

  const handleInputKeyDown = useCallback((event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== 'Escape') return
    setLocalQuery('')
    draftRef.current = ''
    onDraftChange?.('')
    event.currentTarget.blur()
  }, [onDraftChange])

  const home = presentation === 'home'
  const cortex = presentation === 'cortex'
  const wrapperClassName = 'w-full max-w-full'
  const queryActive = isSubmitting || submissionPending
  const cortexStateClassName = queryActive
    ? 'border-[#A855F7]/70'
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
    <form onSubmit={handleSubmit} className={formClassName} aria-label="Ask APEX" aria-busy={isSubmitting || submissionPending}>
      {cortex && queryActive ? <CortexQueryRim /> : null}
      <div className={`flex items-center gap-3 ${cortex ? 'min-h-12 px-3 py-2 sm:min-h-14 sm:px-4' : 'min-h-10 px-2 py-1'}`}>
        <span className="shrink-0 font-mono text-sm font-semibold text-[#0F4DB8]" aria-hidden>&gt;_</span>
        <input type="text" value={query} onChange={(event) => { draftRef.current = event.target.value; setLocalQuery(event.target.value); onDraftChange?.(event.target.value) }} onKeyDown={handleInputKeyDown} placeholder="Ask APEX" disabled={editorDisabled} className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none focus:ring-0" aria-label="Ask APEX query" autoComplete="off" spellCheck={false} />
        <ToolsSelector compact={home} catalog={catalog} selectedToolNames={selectedToolNames} activeToolProfileId={activeToolProfileId} onSelectionChange={onToolSelectionChange ?? (() => undefined)} onProfileChange={onToolProfileChange ?? (() => undefined)} preflight={toolPreflight} preflightLoading={toolPreflightLoading} catalogError={toolCatalogError} preflightError={toolPreflightError} profileFeedback={toolProfileFeedback} profileError={toolProfileError} disabled={editorDisabled} onSaveProfile={onSaveToolProfile} onDuplicateProfile={onDuplicateToolProfile} onRenameProfile={onRenameToolProfile} onDeleteProfile={onDeleteToolProfile} onRestoreProfile={onRestoreToolProfile} onSetDefaultProfile={onSetDefaultToolProfile} />
        {!home ? <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[10px] text-zinc-400" aria-label={`Active agent ${activeAgentName}`}><AgentMark agent={activeAgent} /><span className="hidden sm:inline">{activeAgentName}</span></span> : null}
        <button type="submit" disabled={submitDisabled} className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#7E22CE]/45 bg-[#7E22CE]/15 text-[#E9D5FF] transition-colors hover:border-[#C084FC] hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-40" aria-label={isSubmitting ? 'Sending query' : submissionPending ? 'Preparing query' : 'Send query'}>{isSubmitting || submissionPending ? <Loader2 className="cortex-query-spinner size-3.5" aria-hidden /> : <Send className="size-3.5" aria-hidden />}</button>
      </div>
      {cortex && error ? <CortexErrorFeedback key={error} error={error} /> : null}
    </form>
  </div>
}
