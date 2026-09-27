import { Check, ChevronDown, X } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { formatBriefingTime } from '../../lib/briefingFormat'
import { formatAgentPricing, formatReasoningLabel, providerDisplayName } from '../../lib/agents'
import type {
  BriefingProfileId,
  BriefingProfileSummary,
  BriefingSessionDetail,
  BriefingSessionSummary,
} from '../../types/briefings'
import type { CloudEffort, LocalReasoningMode, ModelCatalogEntry } from '../../types/telemetry'
import { LocalModelControl } from '../LocalModelControl'
import { ModelMark } from '../ModelMark'
import { StabilityBadge } from '../StabilityBadge'
import { BriefingCoverage } from './BriefingEvidence'

const FALLBACK_PROFILES: BriefingProfileSummary[] = [
  { id: 'daily', label: 'Daily', purpose: 'A concise view of current information.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'catch_up', label: 'Catch Up', purpose: 'What changed since the last presented briefing.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation across relevant current information and context.', investigation_required: true, available: true, unavailable_reason: null },
]

const RUNNING_STATUSES = new Set(['queued', 'running', 'cancelling'])
const SELECTABLE_MODEL_STATUSES = new Set(['available', 'configured', 'verified', 'unknown'])

export type BriefingSetupDraft = {
  profileId: BriefingProfileId
  modelId: string
  cloudEffort: CloudEffort | null
  localReasoningMode: LocalReasoningMode | null
}

export type BriefingProfilePanelProps = {
  actionLayout?: 'row' | 'column'
  profiles: BriefingProfileSummary[]
  profileId: BriefingProfileId
  onProfileChange: (profileId: BriefingProfileId) => void
  selectedModelId: string
  cloudEffort: CloudEffort
  localReasoningMode: LocalReasoningMode
  modelCatalog: ModelCatalogEntry[]
  canGenerate: boolean
  busy: boolean
  hasActiveSession: boolean
  isGenerating: boolean
  onGenerate: (draft: BriefingSetupDraft) => Promise<void>
  onRepeat: () => Promise<void>
  autoOpenSetup: boolean
  onAutoOpenSetupConsumed: () => void
  demoModeActive?: boolean
  onCancel: (sessionId: string) => void
  sessions: BriefingSessionSummary[]
  selectedSessionId: string | null
  isLoadingSessions: boolean
  onOpenSession: (sessionId: string) => void
  activeSession: BriefingSessionDetail | null
  latestSession: BriefingSessionDetail | null
  latestError: string | null
  isLoadingLatestSession: boolean
  error: string | null
  activeLocalModel: ModelCatalogEntry | null
  loadingLocalModel: ModelCatalogEntry | null
  localLifecycleBusy: boolean
  onUnloadLocalModel: () => Promise<boolean>
  /** Reserved for briefing speech controls. */
  speechControl?: ReactNode
}

function sessionFailureCopy(session: BriefingSessionDetail): string | null {
  if (session.run_status === 'failed' && session.run_error_code === 'invalid_model_output') {
    return `The model response did not pass ${session.configuration.profile.label} validation after one repair attempt. Start a new ${session.configuration.profile.label} run to try again.`
  }
  if (session.run_status === 'failed' || session.run_status === 'interrupted' || session.run_status === 'cancelled') {
    return `This ${session.configuration.profile.label} run ${session.run_status}. It did not produce a completed artifact.`
  }
  return null
}

function modelIsAvailable(model: ModelCatalogEntry): boolean {
  if (model.credentials_configured === false || model.status === 'disabled') return false
  return model.status === undefined || SELECTABLE_MODEL_STATUSES.has(model.status)
}

function supportedLocalModes(model: ModelCatalogEntry): LocalReasoningMode[] {
  return model.reasoning_modes ?? (model.default_reasoning_mode ? [model.default_reasoning_mode] : [])
}

function reasoningSummary(model: ModelCatalogEntry | undefined, draft: BriefingSetupDraft): string {
  if (model?.runtime === 'cloud') {
    const options = model.reasoning_options ?? []
    if (options.length === 0) return 'Not configurable'
    if (draft.cloudEffort && options.includes(draft.cloudEffort)) return formatReasoningLabel(draft.cloudEffort)
    return 'Choose effort'
  }
  if (model?.runtime === 'local') {
    const modes = supportedLocalModes(model)
    if (modes.length === 0) return 'Unavailable'
    if (draft.localReasoningMode && modes.includes(draft.localReasoningMode)) return formatReasoningLabel(draft.localReasoningMode)
    return 'Choose effort'
  }
  return 'Choose model'
}

function initialDraft(props: BriefingProfilePanelProps): BriefingSetupDraft {
  const model = props.modelCatalog.find((entry) => entry.model_id === props.selectedModelId)
  return {
    profileId: props.profileId,
    modelId: props.selectedModelId,
    cloudEffort: model?.runtime === 'cloud' && model.reasoning_options?.includes(props.cloudEffort)
      ? props.cloudEffort
      : null,
    localReasoningMode: model?.runtime === 'local' && supportedLocalModes(model).includes(props.localReasoningMode)
      ? props.localReasoningMode
      : null,
  }
}

function modelSelectionError(
  profile: BriefingProfileSummary,
  model: ModelCatalogEntry | undefined,
  draft: BriefingSetupDraft,
  props: BriefingProfilePanelProps,
): string | null {
  if (!profile.available) return profile.unavailable_reason ?? `${profile.label} is unavailable.`
  if (!props.canGenerate && !props.demoModeActive) return 'Briefings are disabled in Apex Agent settings.'
  if (props.demoModeActive) return null
  if (!model) return 'Select an available Apex Agent model.'
  if (!modelIsAvailable(model)) return `${model.display_name} is not currently available.`
  if (model.runtime === 'cloud' && model.reasoning_options && model.reasoning_options.length > 0) {
    if (!draft.cloudEffort || !model.reasoning_options.includes(draft.cloudEffort)) {
      return 'Choose a reasoning effort supported by this model.'
    }
  }
  if (model.runtime === 'local') {
    const modes = supportedLocalModes(model)
    if (modes.length === 0) return 'This local model has no reported reasoning modes.'
    if (!draft.localReasoningMode || !modes.includes(draft.localReasoningMode)) {
      return 'Choose a reasoning mode supported by this model.'
    }
  }
  return null
}

function repeatUnavailableReason(
  session: BriefingSessionDetail | null,
  latestError: string | null,
  isLoading: boolean,
  props: BriefingProfilePanelProps,
): string | null {
  if (isLoading) return 'Checking the latest saved briefing.'
  if (latestError) return 'The latest saved briefing could not be checked.'
  if (props.hasActiveSession) return 'A briefing is already running.'
  if (!session) return 'No saved briefing history is available to repeat.'
  if (session.configuration.execution_kind === 'demo') {
    if (!props.demoModeActive) return 'This saved fixture is available only in DEMO_MODE.'
    if (session.configuration.profile.id === 'deep') return 'Deep is unavailable in DEMO_MODE.'
    return null
  }
  if (props.demoModeActive) return 'Model-backed sessions cannot be repeated in DEMO_MODE.'
  if (!props.canGenerate) return 'Briefings are disabled in Apex Agent settings.'
  const savedModel = session.configuration.model
  const model = props.modelCatalog.find((entry) => entry.model_id === savedModel.model_id)
  if (!model || !modelIsAvailable(model) || model.runtime !== savedModel.runtime) {
    return 'The model used by this briefing is not currently available.'
  }
  const profile = props.profiles.find((entry) => entry.id === session.configuration.profile.id)
  if (profile && !profile.available) return profile.unavailable_reason ?? `${profile.label} is currently unavailable.`
  if (model.runtime === 'cloud') {
    if (savedModel.local_reasoning_mode !== null) return 'The saved cloud model configuration contains an unsupported local reasoning mode.'
    const options = model.reasoning_options ?? []
    if (savedModel.reasoning === null && options.length > 0) return 'The saved briefing has no cloud reasoning value for the current model.'
    if (savedModel.reasoning !== null && !options.includes(savedModel.reasoning as CloudEffort)) {
      return 'The saved cloud reasoning effort is no longer supported by this model.'
    }
  } else {
    if (savedModel.reasoning !== null) return 'The saved local model configuration contains an unsupported cloud reasoning effort.'
    const modes = supportedLocalModes(model)
    if (!savedModel.local_reasoning_mode || !modes.includes(savedModel.local_reasoning_mode as LocalReasoningMode)) {
      return 'The saved local reasoning mode is no longer supported by this model.'
    }
  }
  return null
}

function errorCopy(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}

export function BriefingProfilePanel(props: BriefingProfilePanelProps): ReactElement {
  const profiles = (props.profiles.length > 0 ? props.profiles : FALLBACK_PROFILES).map((item) => (
    props.demoModeActive && item.id === 'deep'
      ? { ...item, available: false, unavailable_reason: 'Deep is unavailable in DEMO_MODE.' }
      : item
  ))
  const activeProfile = profiles.find((item) => item.id === props.profileId) ?? profiles[0]
  const session = props.activeSession && props.activeSession.id === props.selectedSessionId ? props.activeSession : null
  const runningSession = session && RUNNING_STATUSES.has(session.run_status) ? session : null
  const deepStage = runningSession?.configuration.profile.id === 'deep' ? runningSession.active_stage : null
  const failureCopy = session ? sessionFailureCopy(session) : null
  const [setupOpen, setSetupOpen] = useState(() => props.autoOpenSetup)
  const [draft, setDraft] = useState<BriefingSetupDraft>(() => initialDraft(props))
  const [agentMenuOpen, setAgentMenuOpen] = useState(false)
  const [agentSubmenu, setAgentSubmenu] = useState<'model' | 'effort' | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRepeating, setIsRepeating] = useState(false)
  const [setupError, setSetupError] = useState<string | null>(null)
  const [repeatError, setRepeatError] = useState<string | null>(null)
  const submitGuardRef = useRef(false)
  const repeatGuardRef = useRef(false)
  const setupOpenerRef = useRef<HTMLButtonElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const agentDropdownTriggerRef = useRef<HTMLButtonElement>(null)
  const modelOptionTriggerRef = useRef<HTMLButtonElement>(null)
  const effortOptionTriggerRef = useRef<HTMLButtonElement>(null)
  const agentMenuStateRef = useRef<{ open: boolean; submenu: 'model' | 'effort' | null }>({ open: false, submenu: null })
  const agentMenuId = useId()
  const { autoOpenSetup, onAutoOpenSetupConsumed } = props

  useLayoutEffect(() => {
    agentMenuStateRef.current = { open: agentMenuOpen, submenu: agentSubmenu }
  }, [agentMenuOpen, agentSubmenu])

  const openSetup = (): void => {
    setDraft(initialDraft(props))
    setAgentMenuOpen(false)
    setAgentSubmenu(null)
    setSetupError(null)
    setRepeatError(null)
    setSetupOpen(true)
  }

  useEffect(() => {
    if (!autoOpenSetup) return
    onAutoOpenSetupConsumed()
  }, [autoOpenSetup, onAutoOpenSetupConsumed])

  useLayoutEffect(() => {
    if (!setupOpen) return undefined
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    closeButtonRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        const menuState = agentMenuStateRef.current
        if (menuState.submenu) {
          setAgentSubmenu(null)
          ;(menuState.submenu === 'model' ? modelOptionTriggerRef.current : effortOptionTriggerRef.current)?.focus()
          return
        }
        if (menuState.open) {
          setAgentMenuOpen(false)
          agentDropdownTriggerRef.current?.focus()
          return
        }
        setSetupOpen(false)
        setAgentMenuOpen(false)
        setAgentSubmenu(null)
        setSetupError(null)
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [])].filter((element) => element.getAttribute('aria-hidden') !== 'true')
      if (focusable.length === 0) {
        event.preventDefault()
        dialogRef.current?.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!dialogRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    const setupOpener = setupOpenerRef.current
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      const restoreTarget = setupOpener ?? previousFocusRef.current
      if (restoreTarget?.isConnected) restoreTarget.focus()
    }
  }, [setupOpen])

  const selectedModel = props.modelCatalog.find((entry) => entry.model_id === draft.modelId)
  const profile = profiles.find((item) => item.id === draft.profileId) ?? activeProfile
  const cloudModels = props.modelCatalog.filter((entry) => entry.runtime === 'cloud')
  const localModels = props.modelCatalog.filter((entry) => entry.runtime === 'local')
  const reasoningOptions = selectedModel?.runtime === 'cloud'
    ? selectedModel.reasoning_options ?? []
    : selectedModel?.runtime === 'local' ? supportedLocalModes(selectedModel) : []
  const selectedReasoning = reasoningSummary(selectedModel, draft)
  const selectedProvider = selectedModel ? providerDisplayName(selectedModel.provider) : null
  const profileError = modelSelectionError(profile, selectedModel, draft, props)
  const generateDisabled = Boolean(profileError) || props.busy || props.hasActiveSession || isSubmitting || isRepeating
  const repeatReason = repeatUnavailableReason(props.latestSession, props.latestError, props.isLoadingLatestSession, props)
  const repeatDisabled = props.isLoadingLatestSession || props.hasActiveSession || isRepeating || isSubmitting || props.busy || Boolean(repeatReason && !props.latestError)
  const repeatModelLabel = props.latestSession?.configuration.execution_kind === 'demo'
    ? 'Demo fixture'
    : props.modelCatalog.find((entry) => entry.model_id === props.latestSession?.configuration.model.model_id)?.display_name
      ?? props.latestSession?.configuration.model.model_id
  const latestSummary = props.latestSession
    ? `${props.latestSession.configuration.profile.label} · ${repeatModelLabel} · ${props.latestSession.run_status} · ${formatBriefingTime(props.latestSession.created_at)}`
    : props.isLoadingLatestSession ? 'Checking saved briefing history…' : 'No saved briefing history yet.'

  const closeSetup = (): void => {
    setSetupOpen(false)
    setAgentMenuOpen(false)
    setAgentSubmenu(null)
    setSetupError(null)
  }

  const submitDraft = async (): Promise<void> => {
    if (submitGuardRef.current || generateDisabled) return
    submitGuardRef.current = true
    setIsSubmitting(true)
    setSetupError(null)
    setAgentMenuOpen(false)
    setAgentSubmenu(null)
    setSetupOpen(false)
    try {
      await props.onGenerate(draft)
      props.onProfileChange(draft.profileId)
    } catch (cause) {
      setSetupError(errorCopy(cause, 'Briefing could not be started. Adjust this setup and try again.'))
      setSetupOpen(true)
    } finally {
      submitGuardRef.current = false
      setIsSubmitting(false)
    }
  }

  const repeatLast = async (): Promise<void> => {
    if (repeatGuardRef.current || (repeatReason !== null && !props.latestError) || props.isLoadingLatestSession || props.hasActiveSession || props.busy || isSubmitting || isRepeating) return
    repeatGuardRef.current = true
    setIsRepeating(true)
    setRepeatError(null)
    try {
      await props.onRepeat()
    } catch (cause) {
      setRepeatError(errorCopy(cause, 'The latest briefing could not be repeated.'))
    } finally {
      repeatGuardRef.current = false
      setIsRepeating(false)
    }
  }

  const updateDraftModel = (modelId: string): void => {
    const nextModel = props.modelCatalog.find((entry) => entry.model_id === modelId)
    setDraft((current) => ({
      ...current,
      modelId,
      cloudEffort: nextModel?.runtime === 'cloud' && nextModel.reasoning_options?.includes(current.cloudEffort as CloudEffort)
        ? current.cloudEffort
        : null,
      localReasoningMode: nextModel?.runtime === 'local' && supportedLocalModes(nextModel).includes(current.localReasoningMode as LocalReasoningMode)
        ? current.localReasoningMode
        : null,
    }))
  }

  return <section className="flex w-full min-w-0 flex-col gap-3" aria-label="Briefing controls">
    <div className={props.actionLayout === 'column' ? 'grid w-full grid-cols-1 gap-2' : 'grid w-full min-w-0 grid-cols-2 gap-2'}>
      <button
        ref={setupOpenerRef}
        type="button"
        onClick={openSetup}
        disabled={isSubmitting || isRepeating}
        aria-haspopup="dialog"
        aria-expanded={setupOpen}
        className="hud-command-surface inline-flex min-h-10 w-full min-w-0 items-center justify-center rounded-lg border border-[#1F6FE5]/50 bg-[#0F4DB8]/20 px-2 py-2 text-center font-orbitron text-[9px] font-semibold uppercase leading-snug tracking-[0.12em] text-[#DCEAFF] hover:bg-[#0F4DB8]/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
      >
        Set up briefing
      </button>
      <button
        type="button"
        onClick={() => void repeatLast()}
        disabled={repeatDisabled}
        aria-describedby="briefing-repeat-status"
        className="inline-flex min-h-10 w-full min-w-0 items-center justify-center rounded-lg border border-amber-400/25 bg-amber-950/20 px-2 py-2 text-center font-orbitron text-[9px] font-semibold uppercase leading-snug tracking-[0.12em] text-amber-200 hover:border-amber-400/40 hover:bg-amber-400/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:cursor-not-allowed disabled:opacity-45"
      >
        {isRepeating ? 'Repeating…' : 'Repeat last briefing'}
      </button>
    </div>
    <div id="briefing-repeat-status" className="min-w-0 text-[10px] leading-relaxed text-zinc-500" aria-live="polite">
      <p>{latestSummary}</p>
      {repeatReason ? <p>{repeatReason}{props.latestError ? ` ${props.latestError}` : ''}</p> : null}
    </div>
    {repeatError ? <p className="rounded-md border border-red-500/20 bg-red-950/20 px-2 py-1.5 text-xs text-red-200" role="alert">{repeatError}</p> : null}
    {setupOpen && typeof document !== 'undefined' ? createPortal(
      <div
        className="fixed inset-0 z-[var(--z-overlay)] flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6"
        onMouseDown={(event) => { if (event.currentTarget === event.target) closeSetup() }}
        data-slot="briefing-setup-backdrop"
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="briefing-setup-title"
          aria-describedby="briefing-setup-description"
          tabIndex={-1}
          className="hud-corner-brackets hud-glass hud-glass-solid relative flex max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl flex-col overflow-y-auto rounded-2xl border border-[#6EA8FF]/25 p-4 shadow-2xl sm:max-h-[calc(100dvh-3rem)] sm:p-6"
          data-slot="briefing-setup-dialog"
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <header className="mb-5 flex items-start gap-4 border-b border-white/10 pb-4">
            <div className="min-w-0 flex-1">
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-[#6EA8FF]">Briefing configuration</p>
              <h2 id="briefing-setup-title" className="mt-1 font-orbitron text-sm font-semibold uppercase tracking-[0.12em] text-zinc-100 sm:text-base">Set up your briefing</h2>
              <p id="briefing-setup-description" className="mt-2 max-w-2xl text-xs leading-relaxed text-zinc-400">Choose a briefing profile and configure Apex Agent. These choices are saved when you generate.</p>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={closeSetup}
              aria-label="Close briefing setup"
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-zinc-300 hover:border-white/20 hover:bg-white/[0.08] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF]"
            >
              <X className="size-4" aria-hidden />
            </button>
          </header>

          <div className="space-y-5">
            <fieldset>
              <legend className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-300">Briefing profile</legend>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                {profiles.map((item) => <button
                  key={item.id}
                  type="button"
                  aria-pressed={draft.profileId === item.id}
                  disabled={!item.available || isSubmitting}
                  onClick={() => {
                    setDraft((current) => ({ ...current, profileId: item.id }))
                    setAgentMenuOpen(false)
                    setAgentSubmenu(null)
                  }}
                  className={`flex min-h-28 flex-col items-start rounded-xl border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45 ${draft.profileId === item.id ? 'border-[#6EA8FF]/60 bg-[#0F4DB8]/20 shadow-[inset_0_0_18px_rgba(31,111,229,0.12)]' : 'border-white/10 bg-black/20 hover:border-white/20 hover:bg-white/[0.04]'}`}
                >
                  <span className="flex w-full items-center gap-2 font-orbitron text-[10px] uppercase tracking-[0.14em] text-zinc-100">
                    {draft.profileId === item.id ? <Check className="size-3.5 text-[#7EB3FF]" aria-hidden /> : <span className="size-3.5" aria-hidden />}
                    {item.label}
                  </span>
                  <span className="mt-2 text-[11px] leading-relaxed text-zinc-400">{item.purpose}</span>
                  <span className={`mt-auto pt-2 font-mono text-[9px] uppercase tracking-wider ${item.available ? 'text-emerald-300/80' : 'text-amber-200/80'}`}>
                    {item.available ? item.investigation_required ? 'Investigation' : 'Available' : item.unavailable_reason ?? 'Unavailable'}
                  </span>
                </button>)}
              </div>
            </fieldset>

            <div className="min-w-0">
              <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-300">Apex Agent</p>
              <div className="min-w-0">
                <button
                  ref={agentDropdownTriggerRef}
                  type="button"
                  aria-expanded={agentMenuOpen}
                  aria-controls={agentMenuOpen ? agentMenuId : undefined}
                  onClick={() => {
                    setAgentMenuOpen((open) => !open)
                    setAgentSubmenu(null)
                  }}
                  disabled={isSubmitting}
                  className="flex min-h-14 w-full min-w-0 items-center gap-3 rounded-xl border border-white/10 bg-zinc-950/70 px-3 py-2.5 text-left hover:border-[#7EB3FF]/40 hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50"
                >
                  <ModelMark modelId={selectedModel?.model_id ?? draft.modelId} provider={selectedModel?.provider} size={21} />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span className="truncate font-orbitron text-xs font-semibold text-zinc-100">{selectedModel?.display_name ?? 'Choose a model'}</span>
                      {selectedProvider ? <span className="font-mono text-[9px] text-zinc-500">{selectedProvider}</span> : null}
                    </span>
                    <span className="mt-1 block truncate font-mono text-[10px] text-zinc-400">{selectedModel ? formatAgentPricing(selectedModel) : props.demoModeActive ? 'Demo uses saved fixtures' : 'Select a model'}</span>
                  </span>
                  {selectedModel ? <StabilityBadge stability={selectedModel.stability} /> : null}
                  {selectedModel?.dev_only ? <span className="rounded border border-purple-400/30 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider text-purple-200">Dev mode</span> : null}
                  <span className="shrink-0 border-l border-white/10 pl-3 text-right">
                    <span className="block font-mono text-[8px] uppercase tracking-wider text-zinc-500">Effort</span>
                    <span className="block font-mono text-[10px] text-[#DCEAFF]">{selectedReasoning}</span>
                  </span>
                  <ChevronDown className={`size-4 shrink-0 text-zinc-400 transition-transform ${agentMenuOpen ? 'rotate-180 text-[#7EB3FF]' : ''}`} aria-hidden />
                </button>

                {agentMenuOpen ? <div
                  id={agentMenuId}
                  className="mt-2 grid min-w-0 grid-cols-[minmax(6.75rem,0.72fr)_minmax(0,1.28fr)] overflow-hidden rounded-xl border border-white/15 bg-zinc-950/95 shadow-xl"
                  data-slot="briefing-agent-menu"
                >
                  <div role="group" aria-label="Apex Agent options" className="space-y-1 p-2">
                    <button
                      ref={modelOptionTriggerRef}
                      type="button"
                      aria-expanded={agentSubmenu === 'model'}
                      aria-controls={agentSubmenu === 'model' ? `${agentMenuId}-models` : undefined}
                      onClick={() => setAgentSubmenu((current) => current === 'model' ? null : 'model')}
                      disabled={isSubmitting}
                      className={`flex min-h-12 w-full items-center justify-between gap-1 rounded-lg border px-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50 ${agentSubmenu === 'model' ? 'border-[#6EA8FF]/40 bg-[#0F4DB8]/15 text-white' : 'border-transparent text-zinc-300 hover:border-white/10 hover:bg-white/[0.04]'}`}
                    >
                      <span className="min-w-0">
                        <span className="block font-orbitron text-[9px] uppercase tracking-wider">Model</span>
                        <span className="mt-0.5 block truncate font-mono text-[9px] text-zinc-500">{selectedModel?.display_name ?? 'Select one'}</span>
                      </span>
                      <ChevronDown className="size-3.5 shrink-0 -rotate-90" aria-hidden />
                    </button>
                    <button
                      ref={effortOptionTriggerRef}
                      type="button"
                      aria-expanded={agentSubmenu === 'effort'}
                      aria-controls={agentSubmenu === 'effort' ? `${agentMenuId}-effort` : undefined}
                      onClick={() => setAgentSubmenu((current) => current === 'effort' ? null : 'effort')}
                      disabled={isSubmitting}
                      className={`flex min-h-12 w-full items-center justify-between gap-1 rounded-lg border px-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50 ${agentSubmenu === 'effort' ? 'border-[#6EA8FF]/40 bg-[#0F4DB8]/15 text-white' : 'border-transparent text-zinc-300 hover:border-white/10 hover:bg-white/[0.04]'}`}
                    >
                      <span className="min-w-0">
                        <span className="block font-orbitron text-[9px] uppercase tracking-wider">Effort</span>
                        <span className="mt-0.5 block truncate font-mono text-[9px] text-zinc-500">{selectedReasoning}</span>
                      </span>
                      <ChevronDown className="size-3.5 shrink-0 -rotate-90" aria-hidden />
                    </button>
                  </div>

                  <div className="min-h-32 min-w-0 max-h-[min(48vh,24rem)] overflow-y-auto border-l border-white/10 bg-black/20 p-2 scrollbar-thin">
                    {agentSubmenu === 'model' ? <div id={`${agentMenuId}-models`} role="group" aria-label="Apex Agent model choices" className="space-y-3">
                      {([['Cloud models', cloudModels], ['Local models', localModels]] as const).map(([label, models]) => models.length > 0 ? <section key={label} role="group" aria-label={label} className="space-y-1.5">
                        <p className="px-1 font-mono text-[9px] uppercase tracking-[0.14em] text-zinc-500">{label}</p>
                        {models.map((model) => {
                          const available = modelIsAvailable(model)
                          const provider = providerDisplayName(model.provider)
                          return <button
                            key={model.model_id}
                            type="button"
                            aria-pressed={model.model_id === draft.modelId}
                            disabled={!available || isSubmitting}
                            onClick={() => {
                              updateDraftModel(model.model_id)
                              setAgentSubmenu(null)
                            }}
                            className={`w-full min-w-0 rounded-lg border p-2 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45 ${model.model_id === draft.modelId ? 'border-[#7EB3FF]/45 bg-[#0F4DB8]/15' : 'border-white/5 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]'}`}
                          >
                            <span className="flex min-w-0 items-start gap-1.5">
                              <ModelMark modelId={model.model_id} provider={model.provider} size={16} />
                              <span className="min-w-0 flex-1">
                                <span className="flex flex-wrap items-center gap-1">
                                  <span className="font-orbitron text-[10px] font-semibold text-zinc-100">{model.display_name}</span>
                                  <StabilityBadge stability={model.stability} />
                                  {model.dev_only ? <span className="rounded border border-purple-400/30 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider text-purple-200">Dev mode</span> : null}
                                </span>
                                <span className="mt-0.5 block font-mono text-[9px] text-zinc-500">{provider}{available ? '' : ' · Unavailable'}</span>
                              </span>
                              {model.model_id === draft.modelId ? <Check className="size-3.5 shrink-0 text-[#39FF88]" aria-hidden /> : null}
                            </span>
                            <span className="mt-1.5 block font-mono text-[9px] leading-relaxed text-zinc-400">{formatAgentPricing(model)}</span>
                          </button>
                        })}
                      </section> : null)}
                      {props.modelCatalog.length === 0 ? <p className="px-1 py-2 text-[10px] leading-relaxed text-zinc-500">{props.demoModeActive ? 'Demo uses saved fixtures.' : 'No cloud or local models are available.'}</p> : null}
                    </div> : agentSubmenu === 'effort' ? <div id={`${agentMenuId}-effort`} role="group" aria-label="Reasoning effort choices" className="space-y-1">
                      <p className="mb-2 px-1 font-mono text-[9px] uppercase tracking-[0.14em] text-zinc-500">{selectedModel?.runtime === 'local' ? 'Local reasoning mode' : 'Reasoning effort'}</p>
                      {reasoningOptions.length > 0 ? reasoningOptions.map((option) => {
                        const isSelected = selectedModel?.runtime === 'cloud'
                          ? draft.cloudEffort === option
                          : draft.localReasoningMode === option
                        return <button
                          key={option}
                          type="button"
                          aria-pressed={isSelected}
                          disabled={isSubmitting}
                          onClick={() => {
                            if (selectedModel?.runtime === 'cloud') {
                              setDraft((current) => ({ ...current, cloudEffort: option as CloudEffort }))
                            } else if (selectedModel?.runtime === 'local') {
                              setDraft((current) => ({ ...current, localReasoningMode: option as LocalReasoningMode }))
                            }
                            setAgentSubmenu(null)
                          }}
                          className={`flex min-h-10 w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-2 text-left font-mono text-[10px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50 ${isSelected ? 'border-[#7EB3FF]/45 bg-[#0F4DB8]/15 text-[#DCEAFF]' : 'border-white/5 text-zinc-300 hover:border-white/15 hover:bg-white/[0.04]'}`}
                        >
                          {formatReasoningLabel(option)}
                          {isSelected ? <Check className="size-3.5 text-[#39FF88]" aria-hidden /> : null}
                        </button>
                      }) : <p className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 text-[10px] leading-relaxed text-zinc-400">{selectedModel?.runtime === 'cloud' ? 'This model has no configurable reasoning effort.' : selectedModel?.runtime === 'local' ? 'This model has no reported reasoning modes.' : 'Choose a model to see its reasoning options.'}</p>}
                    </div> : <p className="flex min-h-32 items-center justify-center px-2 text-center text-[10px] leading-relaxed text-zinc-500">Choose Model or Effort to configure Apex Agent.</p>}
                  </div>
                </div> : null}
              </div>
            </div>
            {props.demoModeActive ? <p className="rounded-lg border border-amber-400/15 bg-amber-950/15 px-3 py-2 text-[11px] leading-relaxed text-amber-100/80">DEMO_MODE generates from saved fixtures. Model choices are not sent to a provider.</p> : null}
            {profileError ? <p className="text-[11px] leading-relaxed text-amber-100/80" role="status">{profileError}</p> : null}
            {setupError ? <p className="rounded-md border border-red-500/20 bg-red-950/20 px-3 py-2 text-xs text-red-200" role="alert">{setupError}</p> : null}
          </div>

          <footer className="sticky bottom-[-1rem] -mx-4 mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-white/10 bg-zinc-950/95 px-4 py-3 sm:bottom-[-1.5rem] sm:-mx-6 sm:px-6">
            <button type="button" onClick={closeSetup} disabled={isSubmitting} className="min-h-10 rounded-lg border border-white/10 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-300 hover:bg-white/[0.06] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50">Close</button>
            <button
              type="button"
              onClick={() => void submitDraft()}
              disabled={generateDisabled}
              title={profileError ?? (props.hasActiveSession ? 'Wait for the active briefing to finish.' : undefined)}
              className="hud-command-surface min-h-10 rounded-lg border border-[#1F6FE5]/60 bg-[#0F4DB8]/30 px-5 py-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[#E5F0FF] shadow-[0_0_18px_rgba(31,111,229,0.18)] hover:bg-[#0F4DB8]/45 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isSubmitting || props.isGenerating ? 'Starting…' : `Generate ${profile.label}`}
            </button>
          </footer>
        </div>
      </div>,
      document.body,
    ) : null}

    {runningSession ? <button
      type="button"
      disabled={runningSession.run_status === 'cancelling'}
      onClick={() => props.onCancel(runningSession.id)}
      className="self-start rounded-lg border border-red-500/25 px-3 py-2 font-orbitron text-[10px] uppercase tracking-[0.14em] text-red-200 hover:bg-red-950/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-300 disabled:opacity-40"
    >
      Cancel
    </button> : null}
    <div className="flex flex-wrap items-center gap-2">
      <LocalModelControl
        model={props.activeLocalModel}
        loadingModel={props.loadingLocalModel}
        busy={props.localLifecycleBusy}
        onUnload={props.onUnloadLocalModel}
        presentation="rail"
      />
      {props.speechControl}
    </div>
    {runningSession ? <p className="animate-pulse font-mono text-[10px] uppercase tracking-wider text-[#A5C7FF] motion-reduce:animate-none" role="status">
      {runningSession.configuration.profile.id === 'deep'
        ? deepStage?.stage === 'investigating'
          ? 'Deep is checking relevant read sources…'
          : deepStage?.stage === 'synthesizing'
            ? 'Deep is preparing its evidence-backed briefing…'
            : 'Deep is collecting the briefing snapshot…'
        : `Preparing ${runningSession.configuration.profile.label} from the available snapshot…`}
    </p> : null}
    {props.error && !setupOpen ? <p className="rounded-md border border-red-500/20 bg-red-950/20 px-2 py-1.5 text-xs text-red-200" role="alert">{props.error}</p> : null}
    {failureCopy ? <p className="rounded-md border border-amber-400/20 bg-amber-950/15 px-2 py-1.5 text-xs text-amber-100" role="alert">{failureCopy}</p> : null}
    {session?.artifact ? <BriefingCoverage artifact={session.artifact} /> : null}
    <nav aria-label="Saved briefing sessions" className="min-w-0">
      <p className="mb-1.5 font-mono text-[9px] uppercase tracking-wider text-zinc-500">Saved sessions</p>
      {props.isLoadingSessions && props.sessions.length === 0 ? <p className="text-[10px] text-zinc-500" role="status">Loading saved sessions…</p> : props.sessions.length === 0 ? <p className="text-[10px] text-zinc-500">No saved briefing sessions yet.</p> : <ul className="max-h-40 space-y-1 overflow-y-auto pr-1 scrollbar-thin">
        {props.sessions.map((item) => <li key={item.id}>
          <button
            type="button"
            onClick={() => props.onOpenSession(item.id)}
            aria-current={item.id === props.selectedSessionId ? 'true' : undefined}
            className={`flex w-full items-center justify-between gap-2 rounded-md border px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] ${item.id === props.selectedSessionId ? 'border-[#1F6FE5]/50 bg-[#0F4DB8]/20 text-white' : 'border-white/10 text-zinc-400 hover:text-white'}`}
          >
            <span className="min-w-0 truncate font-mono text-[10px]">{profiles.find((entry) => entry.id === item.profile_id)?.label ?? item.profile_id} · {formatBriefingTime(item.created_at)}</span>
            <span className="shrink-0 text-[9px] capitalize">{item.run_status}</span>
          </button>
        </li>)}
      </ul>}
    </nav>
  </section>
}
