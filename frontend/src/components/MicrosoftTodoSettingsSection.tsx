import type { ReactElement } from 'react'
import { ExternalLink } from 'lucide-react'

import type { useMicrosoftTodoStatus } from '../hooks/useMicrosoftTodoStatus'
import { SectionHeading, StatusRow, type SettingsStatusTone } from './SettingsControls'

type TodoRuntime = ReturnType<typeof useMicrosoftTodoStatus>

const LABELS: Record<string, { value: string; tone: SettingsStatusTone }> = {
  'not-configured': { value: 'Not configured', tone: 'neutral' },
  disconnected: { value: 'Disconnected', tone: 'neutral' },
  authorizing: { value: 'Waiting for sign-in', tone: 'warn' },
  connected: { value: 'Connected', tone: 'ok' },
  'authentication-required': { value: 'Authentication required', tone: 'warn' },
  degraded: { value: 'Degraded', tone: 'error' },
}

export default function MicrosoftTodoSettingsSection({
  sectionId,
  runtime,
}: {
  sectionId: string
  runtime: TodoRuntime
}): ReactElement {
  const presentation = runtime.status
    ? LABELS[runtime.status.state]
    : { value: runtime.error ? 'Status unavailable' : 'Checking…', tone: 'neutral' as const }
  const connected = runtime.status?.state === 'connected'
  const canConnect = Boolean(runtime.status?.configured) && !connected

  return (
    <section className="space-y-2.5" aria-labelledby={sectionId}>
      <SectionHeading id={sectionId} title="Microsoft To Do — Read Only" />
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Lets the assistant read task lists and tasks with Tasks.Read. APEX reminders remain in the local SQLite ledger.
      </p>
      <div className="rounded-lg border border-white/5 bg-white/[0.015] p-2.5">
        <StatusRow label="Connection" value={presentation.value} tone={presentation.tone} />
        {runtime.authorization ? (
          <div className="mt-2 space-y-2 rounded-md border border-amber-400/20 bg-amber-500/5 p-2.5">
            <p className="text-[11px] text-zinc-300">Enter this one-time code on Microsoft’s sign-in page:</p>
            <p className="font-mono text-base tracking-[0.2em] text-amber-100">{runtime.authorization.user_code}</p>
            <a
              href={runtime.authorization.verification_uri}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[color:var(--hud-accent)] underline-offset-2 hover:underline"
            >
              Open Microsoft sign-in <ExternalLink className="size-3" aria-hidden />
            </a>
          </div>
        ) : null}
        {runtime.error ? <p className="mt-2 text-[11px] text-red-300" role="status">{runtime.error}</p> : null}
        {!runtime.status?.configured ? (
          <p className="mt-2 text-[10px] text-zinc-500">Set MICROSOFT_TODO_CLIENT_ID to enable connection.</p>
        ) : null}
        <div className="mt-2 flex gap-2">
          {canConnect ? (
            <button
              type="button"
              disabled={runtime.loading || runtime.status?.state === 'authorizing'}
              onClick={() => void runtime.connect()}
              className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-200 disabled:opacity-50"
            >
              Connect
            </button>
          ) : null}
          {connected || runtime.status?.state === 'authorizing' ? (
            <button
              type="button"
              disabled={runtime.loading}
              onClick={() => void runtime.disconnect()}
              className="rounded-md border border-red-400/20 bg-red-500/5 px-2.5 py-1.5 text-xs text-red-200 disabled:opacity-50"
            >
              Disconnect
            </button>
          ) : null}
        </div>
      </div>
    </section>
  )
}
