import { Check, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { formatBriefingTime } from '../../lib/briefingFormat'
import { formatReasoningLabel, providerDisplayName } from '../../lib/agents'
import type {
  BriefingProfileId,
  BriefingProfileSummary,
  BriefingSessionDetail,
  BriefingSessionSummary,
} from '../../types/briefings'
import type { CloudEffort, LocalReasoningMode, ModelCatalogEntry } from '../../types/telemetry'
import { LocalModelControl } from '../LocalModelControl'
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
  const { autoOpenSetup, onAutoOpenSetupConsumed } = props

  const openSetup = (): void => {
    setDraft(initialDraft(props))
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
        setSetupOpen(false)
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
    setSetupError(null)
  }

  const submitDraft = async (): Promise<void> => {
    if (submitGuardRef.current || generateDisabled) return
    submitGuardRef.current = true
    setIsSubmitting(true)
    setSetupError(null)
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
    <div className="flex flex-wrap items-start gap-2">
      <button
        ref={setupOpenerRef}
        type="button"
        onClick={openSetup}
        disabled={isSubmitting || isRepeating}
        aria-haspopup="dialog"
        aria-expanded={setupOpen}
        className="hud-command-surface inline-flex min-h-10 items-center justify-center rounded-lg border border-[#1F6FE5]/50 bg-[#0F4DB8]/20 px-3.5 py-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[#DCEAFF] hover:bg-[#0F4DB8]/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
      >
        Set up briefing
      </button>
      <button
        type="button"
        onClick={() => void repeatLast()}
        disabled={repeatDisabled}
        aria-describedby="briefing-repeat-status"
        className="inline-flex min-h-10 min-w-0 flex-1 items-center justify-center rounded-lg border border-amber-400/25 bg-amber-950/20 px-3 py-2 text-left font-orbitron text-[9px] font-semibold uppercase tracking-[0.12em] text-amber-200 hover:border-amber-400/40 hover:bg-amber-400/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:cursor-not-allowed disabled:opacity-45"
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
              <p id="briefing-setup-description" className="mt-2 max-w-2xl text-xs leading-relaxed text-zinc-400">Choose a briefing profile and an Apex Agent model. These choices are saved when you generate.</p>
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
                  onClick={() => setDraft((current) => ({ ...current, profileId: item.id }))}
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

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="min-w-0">
                <label htmlFor="briefing-setup-model" className="mb-2 block font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-300">Apex Agent model</label>
                <select
                  id="briefing-setup-model"
                  value={selectedModel ? draft.modelId : ''}
                  onChange={(event) => updateDraftModel(event.target.value)}
                  disabled={isSubmitting}
                  className="min-h-11 w-full rounded-lg border border-white/10 bg-zinc-950/90 px-3 py-2 font-mono text-xs text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50"
                >
                  <option value="" disabled>{props.demoModeActive && props.modelCatalog.length === 0 ? 'Demo uses saved fixtures' : 'Select a model'}</option>
                  {cloudModels.length > 0 ? <optgroup label="Cloud">
                    {cloudModels.map((model) => <option key={model.model_id} value={model.model_id} disabled={!modelIsAvailable(model)}>
                      {model.display_name}{modelIsAvailable(model) ? '' : ' · unavailable'}
                    </option>)}
                  </optgroup> : null}
                  {localModels.length > 0 ? <optgroup label="Local">
                    {localModels.map((model) => <option key={model.model_id} value={model.model_id} disabled={!modelIsAvailable(model)}>
                      {model.display_name}{modelIsAvailable(model) ? '' : ' · unavailable'}
                    </option>)}
                  </optgroup> : null}
                </select>
                {selectedModel ? <p className="mt-1.5 text-[10px] text-zinc-500">{providerDisplayName(selectedModel.provider)} · {selectedModel.runtime === 'cloud' ? 'Cloud model' : 'Runs on this device'}</p> : null}
              </div>

              {selectedModel?.runtime === 'cloud' ? (
                <div className="min-w-0">
                  <label htmlFor="briefing-setup-cloud-effort" className="mb-2 block font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-300">Cloud reasoning effort</label>
                  {selectedModel.reasoning_options && selectedModel.reasoning_options.length > 0 ? <select
                    id="briefing-setup-cloud-effort"
                    value={draft.cloudEffort ?? ''}
                    onChange={(event) => setDraft((current) => ({ ...current, cloudEffort: event.target.value as CloudEffort || null }))}
                    disabled={isSubmitting}
                    className="min-h-11 w-full rounded-lg border border-white/10 bg-zinc-950/90 px-3 py-2 font-mono text-xs text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50"
                  >
                    <option value="" disabled>Select a supported effort</option>
                    {selectedModel.reasoning_options.map((effort) => <option key={effort} value={effort}>{formatReasoningLabel(effort)}</option>)}
                  </select> : <p className="flex min-h-11 items-center rounded-lg border border-white/10 bg-black/20 px-3 text-xs text-zinc-400">This model has no configurable reasoning effort.</p>}
                </div>
              ) : selectedModel?.runtime === 'local' ? (
                <div className="min-w-0">
                  <label htmlFor="briefing-setup-local-reasoning" className="mb-2 block font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-300">Local reasoning mode</label>
                  {supportedLocalModes(selectedModel).length > 0 ? <select
                    id="briefing-setup-local-reasoning"
                    value={draft.localReasoningMode ?? ''}
                    onChange={(event) => setDraft((current) => ({ ...current, localReasoningMode: (event.target.value as LocalReasoningMode) || null }))}
                    disabled={isSubmitting}
                    className="min-h-11 w-full rounded-lg border border-white/10 bg-zinc-950/90 px-3 py-2 font-mono text-xs text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:opacity-50"
                  >
                    <option value="" disabled>Select a supported mode</option>
                    {supportedLocalModes(selectedModel).map((mode) => <option key={mode} value={mode}>{formatReasoningLabel(mode)}</option>)}
                  </select> : <p className="flex min-h-11 items-center rounded-lg border border-white/10 bg-black/20 px-3 text-xs text-amber-100">This model has no reported reasoning modes.</p>}
                </div>
              ) : <div className="flex min-h-11 items-center text-xs text-zinc-500">Choose a model to see its reasoning controls.</div>}
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
