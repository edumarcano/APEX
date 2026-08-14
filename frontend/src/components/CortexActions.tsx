import { Check, ChevronDown, Loader2, RotateCcw, ShieldAlert, X } from 'lucide-react'
import { useState, type ReactElement } from 'react'

import type { UseActionsResult } from '../hooks/useActions'
import type { ActionRecord, ActionStatus } from '../types/actions'

const STATUS_CLASS: Record<ActionStatus, string> = {
  proposed: 'border-amber-400/35 bg-amber-950/20 text-amber-100',
  approved: 'border-purple-400/35 bg-purple-950/20 text-purple-100',
  executing: 'border-purple-400/35 bg-purple-950/20 text-purple-100',
  verifying: 'border-purple-400/35 bg-purple-950/20 text-purple-100',
  verified: 'border-emerald-400/35 bg-emerald-950/20 text-emerald-100',
  rejected: 'border-zinc-500/35 bg-zinc-900/50 text-zinc-300',
  expired: 'border-zinc-500/35 bg-zinc-900/50 text-zinc-300',
  execution_failed: 'border-red-400/35 bg-red-950/20 text-red-100',
  verification_failed: 'border-red-400/35 bg-red-950/20 text-red-100',
  outcome_unknown: 'border-amber-400/35 bg-amber-950/20 text-amber-100',
}

function displayStatus(status: ActionStatus): string {
  return status.replaceAll('_', ' ')
}

function displayTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unknown time' : date.toLocaleString()
}

function displayJson(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return 'Structured data unavailable.'
  }
}

function ActionRow({
  action,
  selected,
  onSelect,
}: {
  action: ActionRecord
  selected: boolean
  onSelect: () => void
}): ReactElement {
  return (
    <button
      type="button"
      aria-expanded={selected}
      onClick={onSelect}
      className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${selected ? 'border-[#7EB3FF]/50 bg-[#0F4DB8]/10' : 'border-white/8 bg-white/[0.02] hover:border-white/20'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate text-xs font-medium text-zinc-100">{action.proposal.summary}</span>
        <ChevronDown className={`mt-0.5 size-3.5 shrink-0 text-zinc-500 transition-transform ${selected ? 'rotate-180' : ''}`} aria-hidden />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[9px] uppercase tracking-wide text-zinc-500">
        <span className={action.proposal.risk === 'destructive' ? 'text-red-200' : 'text-[#C084FC]'}>{action.proposal.risk}</span>
        <span>{action.proposal.agent_key}</span>
        <span>{displayTime(action.updated_at)}</span>
      </div>
      <span className={`mt-1.5 inline-flex rounded-full border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide ${STATUS_CLASS[action.status]}`}>
        {displayStatus(action.status)}
      </span>
    </button>
  )
}

export function CortexActions({
  actions,
  demoModeActive,
}: {
  actions: UseActionsResult
  demoModeActive: boolean
}): ReactElement {
  const [confirmation, setConfirmation] = useState<{ actionId: string; version: number } | null>(null)
  const detail = actions.detail
  const selectedRecord = actions.actions.find((action) => action.action_id === actions.selectedActionId) ?? null
  const selected = detail ?? selectedRecord
  const isDestructive = selected?.proposal.risk === 'destructive'

  const isConfirming = Boolean(
    detail && confirmation?.actionId === detail.action_id &&
    confirmation.version === (selectedRecord?.version ?? detail.version) && detail.status === 'proposed',
  )

  const select = (actionId: string): void => {
    setConfirmation(null)
    actions.setSelectedActionId(actions.selectedActionId === actionId ? null : actionId)
  }

  const approve = (): void => {
    if (!detail) return
    if (detail.proposal.risk === 'destructive' && !isConfirming) {
      setConfirmation({ actionId: detail.action_id, version: detail.version })
      return
    }
    setConfirmation(null)
    void actions.resolve('approve')
  }

  return (
    <section className="space-y-2" aria-label="Actions">
      <div className="flex items-center justify-between gap-2">
        <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">Actions</p>
        {demoModeActive ? <span className="font-mono text-[9px] uppercase tracking-wide text-zinc-500">Read only</span> : <span className="rounded-full border border-amber-400/30 bg-amber-950/20 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-amber-100">{actions.pendingCount === 50 ? '50+' : actions.pendingCount} pending</span>}
      </div>
      {demoModeActive ? (
        <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-[11px] leading-relaxed text-zinc-500">
          Actions are unavailable in demo mode.
        </div>
      ) : (
        <>
          {actions.error ? <p className="rounded-lg border border-red-400/25 bg-red-950/15 px-3 py-2 text-[11px] text-red-200" role="alert">{actions.error}</p> : null}
          {actions.isLoading && actions.actions.length === 0 ? <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] p-3 font-mono text-[10px] uppercase tracking-wide text-zinc-500"><Loader2 className="size-3.5 animate-spin" aria-hidden />Loading actions</div> : null}
          {!actions.isLoading && actions.actions.length === 0 && !actions.error ? <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-[11px] leading-relaxed text-zinc-500">No actions have been proposed.</div> : null}
          {actions.actions.length > 0 ? <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">{actions.actions.map((action) => <ActionRow key={action.action_id} action={action} selected={actions.selectedActionId === action.action_id} onSelect={() => select(action.action_id)} />)}</div> : null}
          {selected ? <div className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-3">
            {actions.isDetailLoading ? <p className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wide text-zinc-500"><Loader2 className="size-3.5 animate-spin" aria-hidden />Loading audit</p> : null}
            {detail ? <>
              <div className="space-y-1"><p className="font-mono text-[9px] uppercase tracking-wide text-zinc-500">Target</p><p className="text-xs text-zinc-200">{detail.proposal.target}</p><p className="font-mono text-[9px] text-zinc-500">{detail.proposal.capability_name} · expires {displayTime(detail.proposal.expires_at)}</p></div>
              <div><p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-zinc-500">Frozen arguments</p><pre className="max-h-36 overflow-auto rounded border border-white/5 bg-zinc-950/60 p-2 font-mono text-[10px] leading-relaxed text-zinc-300 scrollbar-thin">{displayJson(detail.proposal.arguments)}</pre></div>
              <div><p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-zinc-500">Audit</p><ol className="max-h-44 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">{detail.events.map((event) => <li key={event.sequence} className="rounded border border-white/5 bg-white/[0.02] p-2"><p className="font-mono text-[9px] text-zinc-300">{event.result_code} · {event.actor}</p><p className="mt-0.5 font-mono text-[9px] text-zinc-600">{displayStatus(event.to_status)} · {displayTime(event.occurred_at)}</p>{Object.keys(event.evidence).length > 0 ? <pre className="mt-1 overflow-auto font-mono text-[9px] leading-relaxed text-zinc-500">{displayJson(event.evidence)}</pre> : null}</li>)}</ol></div>
              {detail.status === 'proposed' ? <div className="space-y-2 border-t border-white/10 pt-3">{isConfirming ? <p className="flex items-start gap-2 text-[11px] leading-relaxed text-red-100"><ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />Confirm this destructive action. It cannot be undone from APEX.</p> : null}<div className="flex flex-wrap gap-2"><button type="button" disabled={actions.mutation !== null} onClick={approve} className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide disabled:cursor-not-allowed disabled:opacity-45 ${isDestructive ? 'border-red-400/45 bg-red-950/25 text-red-100 hover:bg-red-950/45' : 'border-emerald-400/45 bg-emerald-950/25 text-emerald-100 hover:bg-emerald-950/45'}`}>{actions.mutation === 'approve' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Check className="size-3" aria-hidden />}{isConfirming ? 'Confirm approve' : 'Approve'}</button>{isConfirming ? <button type="button" disabled={actions.mutation !== null} onClick={() => setConfirmation(null)} className="inline-flex items-center gap-1 rounded-md border border-white/15 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide text-zinc-300 hover:border-white/30 disabled:opacity-45"><X className="size-3" aria-hidden />Cancel</button> : <button type="button" disabled={actions.mutation !== null} onClick={() => void actions.resolve('reject')} className="inline-flex items-center gap-1 rounded-md border border-white/15 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide text-zinc-300 hover:border-white/30 disabled:opacity-45">{actions.mutation === 'reject' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <X className="size-3" aria-hidden />}Reject</button>}</div></div> : null}
              {detail.status === 'verification_failed' || detail.status === 'outcome_unknown' ? <div className="border-t border-white/10 pt-3"><button type="button" disabled={actions.mutation !== null} onClick={() => void actions.resolve('verify')} className="inline-flex items-center gap-1 rounded-md border border-amber-400/45 bg-amber-950/25 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wide text-amber-100 hover:bg-amber-950/45 disabled:cursor-not-allowed disabled:opacity-45">{actions.mutation === 'verify' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <RotateCcw className="size-3" aria-hidden />}Retry verification</button></div> : null}
            </> : null}
          </div> : null}
        </>
      )}
    </section>
  )
}
