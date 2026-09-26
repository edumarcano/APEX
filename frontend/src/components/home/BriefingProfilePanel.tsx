import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from 'react'

import { formatBriefingTime } from '../../lib/briefingFormat'
import type {
  BriefingProfileId,
  BriefingProfileSummary,
  BriefingSessionDetail,
  BriefingSessionSummary,
} from '../../types/briefings'
import type { ModelCatalogEntry } from '../../types/telemetry'
import { HomeModelSelector } from '../HomeModelSelector'
import { LocalModelControl } from '../LocalModelControl'
import { BriefingCoverage } from './BriefingEvidence'

const FALLBACK_PROFILES: BriefingProfileSummary[] = [{
  id: 'daily',
  label: 'Daily',
  purpose: 'A concise view of current information.',
  investigation_required: false,
  available: true,
  unavailable_reason: null,
}]

const RUNNING_STATUSES = new Set(['queued', 'running', 'cancelling'])

export type BriefingProfilePanelProps = {
  profiles: BriefingProfileSummary[]
  profileId: BriefingProfileId
  onProfileChange: (profileId: BriefingProfileId) => void
  selectedModelId: string
  modelCatalog: ModelCatalogEntry[]
  onModelChange: (modelId: string) => void
  canGenerate: boolean
  busy: boolean
  hasActiveSession: boolean
  isGenerating: boolean
  onGenerate: (profileId: BriefingProfileId) => void
  onCancel: (sessionId: string) => void
  sessions: BriefingSessionSummary[]
  selectedSessionId: string | null
  isLoadingSessions: boolean
  onOpenSession: (sessionId: string) => void
  activeSession: BriefingSessionDetail | null
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

function ProfilePicker({
  profiles,
  profileId,
  disabled,
  onProfileChange,
}: {
  profiles: BriefingProfileSummary[]
  profileId: BriefingProfileId
  disabled: boolean
  onProfileChange: (profileId: BriefingProfileId) => void
}): ReactElement {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listId = useId()
  const selected = profiles.find((profile) => profile.id === profileId) ?? profiles[0]
  useEffect(() => {
    if (!open) return undefined
    const handlePointerDown = (event: PointerEvent): void => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      setOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])
  return <div ref={containerRef} className="relative min-w-0">
    <button
      ref={triggerRef}
      type="button"
      disabled={disabled}
      aria-label={`Briefing profile: ${selected?.label ?? 'Daily'}`}
      aria-expanded={open}
      aria-controls={listId}
      onClick={() => setOpen((current) => !current)}
      className="hud-command-surface inline-flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 font-orbitron text-[10px] uppercase tracking-[0.14em] text-zinc-200 hover:border-[#6EA8FF]/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
    >
      <span className="truncate">{selected?.label ?? 'Daily'}</span>
      <ChevronDown className="size-3.5 shrink-0" aria-hidden />
    </button>
    {open ? <div
      id={listId}
      role="radiogroup"
      aria-label="Briefing profiles"
      className="absolute left-0 right-0 top-full z-[var(--z-overlay)] mt-1 space-y-1 rounded-lg border border-white/10 bg-zinc-950 p-1.5 shadow-2xl"
    >
      {profiles.map((profile) => <button
        key={profile.id}
        type="button"
        role="radio"
        aria-checked={profile.id === profileId}
        disabled={!profile.available}
        onClick={() => {
          onProfileChange(profile.id)
          setOpen(false)
          triggerRef.current?.focus()
        }}
        className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Check className={`mt-0.5 size-3 shrink-0 ${profile.id === profileId ? 'text-[#7EB3FF]' : 'invisible'}`} aria-hidden />
        <span className="min-w-0">
          <span className="block font-orbitron text-[10px] uppercase tracking-[0.14em] text-zinc-100">{profile.label}</span>
          <span className="block text-[11px] text-zinc-400">{profile.available ? profile.purpose : profile.unavailable_reason ?? 'Unavailable'}</span>
        </span>
      </button>)}
    </div> : null}
  </div>
}

export function BriefingProfilePanel(props: BriefingProfilePanelProps): ReactElement {
  const profiles = props.profiles.length > 0 ? props.profiles : FALLBACK_PROFILES
  const profile = profiles.find((item) => item.id === props.profileId) ?? profiles[0]
  const session = props.activeSession && props.activeSession.id === props.selectedSessionId ? props.activeSession : null
  const runningSession = session && RUNNING_STATUSES.has(session.run_status) ? session : null
  const deepStage = runningSession?.configuration.profile.id === 'deep' ? runningSession.active_stage : null
  const failureCopy = session ? sessionFailureCopy(session) : null
  const generateDisabled = !props.canGenerate || props.busy || props.hasActiveSession || !profile.available
  return <section className="flex w-full min-w-0 flex-col gap-3" aria-label="Briefing controls">
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <ProfilePicker profiles={profiles} profileId={profile.id} disabled={props.busy} onProfileChange={props.onProfileChange} />
      <HomeModelSelector
        selectedModelId={props.selectedModelId}
        onModelChange={props.onModelChange}
        catalog={props.modelCatalog}
        disabled={props.busy}
        presentation="rail"
      />
    </div>
    {profile.id === 'deep' && profile.available ? <p className="text-[11px] text-zinc-400">Deep can take longer and use more model time while checking a small, read-only set of relevant sources; it may finish without an extra read.</p> : null}
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => props.onGenerate(profile.id)}
        disabled={generateDisabled}
        title={!props.canGenerate ? 'Briefings require an available model or DEMO_MODE.' : undefined}
        className="hud-command-surface inline-flex items-center gap-1.5 rounded-lg border border-[#1F6FE5]/50 bg-[#0F4DB8]/20 px-3.5 py-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[#DCEAFF] hover:bg-[#0F4DB8]/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {props.isGenerating ? 'Starting…' : `Generate ${profile.label}`}
      </button>
      {runningSession ? <button
        type="button"
        disabled={runningSession.run_status === 'cancelling'}
        onClick={() => props.onCancel(runningSession.id)}
        className="rounded-lg border border-red-500/25 px-3 py-2 font-orbitron text-[10px] uppercase tracking-[0.14em] text-red-200 hover:bg-red-950/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-300 disabled:opacity-40"
      >
        Cancel
      </button> : null}
      <LocalModelControl
        model={props.activeLocalModel}
        loadingModel={props.loadingLocalModel}
        busy={props.localLifecycleBusy}
        onUnload={props.onUnloadLocalModel}
        presentation="rail"
      />
      {props.speechControl}
    </div>
    {!profile.available && profile.unavailable_reason ? <p className="text-[11px] text-zinc-500">{profile.unavailable_reason}</p> : null}
    {runningSession ? <p className="animate-pulse font-mono text-[10px] uppercase tracking-wider text-[#A5C7FF] motion-reduce:animate-none" role="status">
      {runningSession.configuration.profile.id === 'deep'
        ? deepStage?.stage === 'investigating'
          ? 'Deep is checking relevant read sources…'
          : deepStage?.stage === 'synthesizing'
            ? 'Deep is preparing its evidence-backed briefing…'
            : 'Deep is collecting the briefing snapshot…'
        : `Preparing ${runningSession.configuration.profile.label} from the available snapshot…`}
    </p> : null}
    {props.error ? <p className="rounded-md border border-red-500/20 bg-red-950/20 px-2 py-1.5 text-xs text-red-200" role="alert">{props.error}</p> : null}
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
