import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Copy,
  Cpu,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import { useState, type ReactElement } from 'react'

import type { UseCortexRunsResult } from '../hooks/useCortexRuns'
import type { RunStatus } from '../types/runs'
import type { AgentStatus } from '../types/telemetry'

export interface CortexActivityProps {
  runsState: UseCortexRunsResult
  agentsStatus?: AgentStatus[]
  className?: string
}

function statusBadgeClass(status: RunStatus): string {
  switch (status) {
    case 'queued':
      return 'border-amber-500/40 bg-amber-950/30 text-amber-300'
    case 'running':
      return 'border-cyan-500/40 bg-cyan-950/30 text-cyan-300'
    case 'cancelling':
      return 'border-red-500/40 bg-red-950/30 text-red-300'
    case 'completed':
      return 'border-emerald-500/40 bg-emerald-950/30 text-emerald-300'
    case 'failed':
      return 'border-red-500/40 bg-red-950/30 text-red-400'
    case 'cancelled':
    case 'interrupted':
      return 'border-zinc-500/40 bg-zinc-900 text-zinc-400'
    default:
      return 'border-zinc-500/30 bg-zinc-900 text-zinc-400'
  }
}

function statusIcon(status: RunStatus): ReactElement {
  switch (status) {
    case 'running':
    case 'cancelling':
      return <Loader2 className="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
    case 'completed':
      return <CheckCircle2 className="size-3" aria-hidden="true" />
    case 'failed':
      return <XCircle className="size-3" aria-hidden="true" />
    case 'queued':
      return <Clock className="size-3" aria-hidden="true" />
    default:
      return <AlertTriangle className="size-3" aria-hidden="true" />
  }
}

function formatDuration(ms?: number | null): string {
  if (ms == null || isNaN(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

function LimitGauge({
  label,
  value,
  max,
  unit = '',
}: {
  label: string
  value: number
  max: number
  unit?: string
}): ReactElement {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  const isHigh = percent >= 85
  const barColor = isHigh ? 'bg-amber-400' : 'bg-[#7EB3FF]'

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] font-mono">
        <span className="text-zinc-400">{label}</span>
        <span className="text-zinc-300 tabular-nums">
          {value}
          {unit} / {max}
          {unit} ({percent}%)
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}

function findResidentLocalModel(agentsStatus: AgentStatus[]): { agent: AgentStatus; model: NonNullable<AgentStatus['model_catalog']>[number] } | null {
  for (const agent of agentsStatus) {
    const active = agent.model_catalog?.find((m) => m.runtime === 'local' && m.active)
    if (active) return { agent, model: active }
  }
  return null
}

export function CortexActivity({
  runsState,
  agentsStatus = [],
  className = '',
}: CortexActivityProps): ReactElement {
  const { runs, selectedRunId, selectedRun, selectRun, refreshRuns, loading } = runsState
  const [copied, setCopied] = useState(false)

  const residentLocalModel = findResidentLocalModel(agentsStatus)

  const handleCopyId = async (id: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard write fallback
    }
  }

  return (
    <section
      aria-label="Cortex Activity"
      className={`space-y-3.5 text-xs font-sans text-zinc-300 ${className}`}
      data-testid="cortex-activity-panel"
    >
      {/* Top Header & Refresh */}
      <div className="flex items-center justify-between border-b border-white/10 pb-2">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-cyan-400" aria-hidden="true" />
          <h3 className="font-mono text-xs uppercase tracking-wider text-zinc-200">
            Cortex Live Activity
          </h3>
          <span className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
            {runs.length} {runs.length === 1 ? 'run' : 'runs'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void refreshRuns()}
          disabled={loading}
          aria-label="Refresh runs"
          className="flex items-center gap-1 rounded border border-white/10 bg-white/[0.02] px-2 py-1 font-mono text-[11px] text-zinc-400 hover:text-white hover:border-white/20 transition-colors disabled:opacity-40"
        >
          <RefreshCw className={`size-3 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          <span>Refresh</span>
        </button>
      </div>

      {runs.length === 0 ? (
        <div className="rounded-lg border border-white/5 bg-white/[0.02] p-6 text-center text-zinc-400">
          <p>No Cortex runs recorded yet.</p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Launch a prompt in the conversation thread to see live telemetry and execution measurements.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Top Run Selector Dropdown */}
          <div className="space-y-1.5">
            <label htmlFor="cortex-run-selector" className="font-mono text-[10px] uppercase tracking-wider text-zinc-500 block">
              Select Run ({runs.length})
            </label>
            <div className="relative">
              <select
                id="cortex-run-selector"
                aria-label="Select run"
                value={selectedRunId ?? ''}
                onChange={(e) => selectRun(e.target.value)}
                className="w-full appearance-none rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 pr-8 font-mono text-xs text-zinc-200 outline-none focus:border-[#7EB3FF] transition-colors cursor-pointer"
              >
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    [{run.status.toUpperCase()}] {run.resolved_model || run.requested_model} · {new Date(run.created_at).toLocaleTimeString()}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-zinc-400">
                <ChevronDown className="size-3.5" aria-hidden="true" />
              </div>
            </div>
          </div>

          {/* Selected Run Details */}
          {selectedRun ? (
            <div className="space-y-3">
              {/* Run Overview Card */}
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3.5 space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider font-semibold ${statusBadgeClass(
                          selectedRun.status,
                        )}`}
                      >
                        {statusIcon(selectedRun.status)}
                        {selectedRun.status}
                      </span>
                      <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-400 px-1.5 py-0.5 rounded bg-white/5 border border-white/5">
                        {selectedRun.runtime ?? 'cloud'}
                      </span>
                    </div>
                    <h4 className="text-sm font-semibold font-mono text-zinc-100 truncate">
                      {selectedRun.resolved_model || selectedRun.requested_model}
                    </h4>
                  </div>
                </div>

                {/* Run ID with copy affordance */}
                <div className="flex items-center justify-between gap-2 rounded bg-black/30 border border-white/5 px-2.5 py-1.5 font-mono text-[10px] text-zinc-400">
                  <span className="truncate">
                    ID: <span className="text-zinc-300">{selectedRun.id.slice(0, 8)}…{selectedRun.id.slice(-4)}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => void handleCopyId(selectedRun.id)}
                    aria-label="Copy run ID"
                    className="flex items-center gap-1 text-zinc-400 hover:text-[#7EB3FF] transition-colors shrink-0"
                    title="Copy full run ID"
                  >
                    {copied ? (
                      <>
                        <Check className="size-3 text-emerald-400" aria-hidden="true" />
                        <span className="text-emerald-400 text-[9px]">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="size-3" aria-hidden="true" />
                        <span className="text-[9px]">Copy</span>
                      </>
                    )}
                  </button>
                </div>

                {/* 2-Column Overview Metrics */}
                <div className="grid grid-cols-2 gap-2 text-[11px] font-mono pt-1 border-t border-white/5">
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase">Provider</span>
                    <span className="text-zinc-200 truncate block">{selectedRun.provider ?? '—'}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase">Total Tokens</span>
                    <span className="text-zinc-200 font-semibold block">{selectedRun.total_tokens}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase">Usage Quality</span>
                    <span className="text-zinc-200 block">{selectedRun.usage_quality}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase">Stop Reason</span>
                    <span className="text-zinc-200 truncate block">{selectedRun.stop_reason ?? '—'}</span>
                  </div>
                </div>
              </div>

              {/* Limit Consumption Gauges */}
              {selectedRun.limit_snapshot && (
                <div className="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-3.5">
                  <h4 className="font-mono text-[10px] uppercase tracking-wider text-zinc-400">
                    Limit Consumption
                  </h4>
                  <div className="space-y-2.5">
                    <LimitGauge
                      label="Turns"
                      value={selectedRun.turns_count}
                      max={selectedRun.limit_snapshot.max_model_turns}
                    />
                    <LimitGauge
                      label="Tool Invocations"
                      value={selectedRun.tool_calls_count}
                      max={selectedRun.limit_snapshot.max_tool_calls}
                    />
                    <LimitGauge
                      label="Retries"
                      value={selectedRun.retries_count}
                      max={selectedRun.limit_snapshot.max_retries}
                    />
                    <LimitGauge
                      label="Tokens"
                      value={selectedRun.total_tokens}
                      max={selectedRun.limit_snapshot.max_total_tokens}
                    />
                    <LimitGauge
                      label="Elapsed Time"
                      value={Math.round(selectedRun.elapsed_seconds)}
                      max={selectedRun.limit_snapshot.max_elapsed_seconds}
                      unit="s"
                    />
                  </div>
                </div>
              )}

              {/* Runtime Measurements */}
              {selectedRun.runtime_measurements && (
                <div className="space-y-2.5 rounded-lg border border-white/10 bg-white/[0.02] p-3.5 font-mono">
                  <h4 className="text-[10px] uppercase tracking-wider text-zinc-400">
                    Runtime Measurements
                  </h4>
                  <div className="grid grid-cols-2 gap-2.5 text-[11px]">
                    <div>
                      <span className="text-zinc-500 block text-[10px]">Queue Time</span>
                      <span className="text-zinc-300 font-semibold">{formatDuration(selectedRun.runtime_measurements.queue_duration_ms)}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500 block text-[10px]">TTFT</span>
                      <span className="text-zinc-300 font-semibold">{formatDuration(selectedRun.runtime_measurements.ttft_ms)}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500 block text-[10px]">Eval Duration</span>
                      <span className="text-zinc-300 font-semibold">{formatDuration(selectedRun.runtime_measurements.eval_duration_ms)}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500 block text-[10px]">Total Duration</span>
                      <span className="text-zinc-300 font-semibold">{formatDuration(selectedRun.runtime_measurements.total_duration_ms)}</span>
                    </div>
                    <div className="col-span-2 pt-1 border-t border-white/5">
                      <span className="text-zinc-500 block text-[10px]">Throughput</span>
                      <span className="text-zinc-200 font-semibold text-xs">
                        {selectedRun.runtime_measurements.tokens_per_second != null
                          ? `${selectedRun.runtime_measurements.tokens_per_second.toFixed(1)} tok/s`
                          : '—'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Tool Evidence & Outcomes */}
              {selectedRun.evidence && (
                <div className="space-y-2.5 rounded-lg border border-white/10 bg-white/[0.02] p-3.5 font-mono text-[11px]">
                  <div className="flex items-center justify-between">
                    <h4 className="text-[10px] uppercase tracking-wider text-zinc-400">
                      Execution Evidence
                    </h4>
                    <span className="text-zinc-500 text-[10px]">
                      Tools: {Object.values(selectedRun.evidence.tool_outcome_counts ?? {}).reduce((a, b) => a + b, 0)}
                    </span>
                  </div>

                  {Object.keys(selectedRun.evidence.tool_outcome_counts ?? {}).length > 0 ? (
                    <div className="space-y-1.5">
                      {Object.entries(selectedRun.evidence.tool_outcome_counts).map(([toolName, count]) => (
                        <div
                          key={toolName}
                          className="flex items-center justify-between rounded bg-black/20 px-2.5 py-1.5 border border-white/5 text-[10px]"
                        >
                          <span className="text-zinc-300 font-semibold">{toolName}</span>
                          <span className="text-zinc-400">{count} call{count === 1 ? '' : 's'}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-zinc-500 text-[10px]">No external tool calls invoked.</p>
                  )}

                  {selectedRun.evidence.action_ids && selectedRun.evidence.action_ids.length > 0 && (
                    <div className="pt-2 border-t border-white/5">
                      <span className="text-zinc-500 text-[10px] block">
                        Actions Proposed ({selectedRun.evidence.action_ids.length}):
                      </span>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {selectedRun.evidence.action_ids.map((actionId) => (
                          <span
                            key={actionId}
                            className="rounded bg-purple-950/40 border border-purple-500/30 px-1.5 py-0.5 text-[10px] text-purple-300 font-mono"
                          >
                            {actionId.slice(0, 8)}…
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Error Callout */}
              {selectedRun.error && (
                <div className="rounded-lg border border-red-500/30 bg-red-950/20 p-3 text-red-300 text-xs">
                  <p className="font-semibold flex items-center gap-1.5 font-mono text-[11px]">
                    <AlertTriangle className="size-3.5" aria-hidden="true" />
                    Execution Error ({selectedRun.error.code})
                  </p>
                  <p className="mt-1 font-mono text-[11px] break-all">{selectedRun.error.message}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4 text-center text-zinc-500">
              Select a run from the list to view telemetry details.
            </div>
          )}
        </div>
      )}

      {/* Resident Local Model (shown only if a local model is active) */}
      {residentLocalModel && (
        <div className="rounded-lg border border-orange-500/25 bg-orange-950/10 p-3 font-mono space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[10px] text-orange-400 uppercase tracking-wider">
              <Cpu className="size-3" aria-hidden="true" />
              Resident Local Model
            </span>
            <span className="text-[10px] text-orange-200/80 bg-orange-500/20 border border-orange-500/30 px-1.5 py-0.5 rounded">
              Active
            </span>
          </div>
          <span className="block font-semibold text-xs text-orange-100 truncate">
            {residentLocalModel.model.model_id}
          </span>
          {residentLocalModel.model.idle_unload_remaining_seconds != null && (
            <span className="text-[10px] text-orange-200/60 block">
              Idle unload in {residentLocalModel.model.idle_unload_remaining_seconds}s
            </span>
          )}
        </div>
      )}
    </section>
  )
}
