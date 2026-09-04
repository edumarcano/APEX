import { Activity, AlertTriangle, CheckCircle2, Clock, Cpu, HardDrive, Loader2, RefreshCw, Square, XCircle } from 'lucide-react'
import type { ReactElement } from 'react'

import { isRunActive, type UseCortexRunsResult } from '../hooks/useCortexRuns'
import type { RunStatus } from '../types/runs'
import type { AgentStatus, SystemDiagnostics } from '../types/telemetry'

export interface CortexActivityProps {
  runsState: UseCortexRunsResult
  agentsStatus?: AgentStatus[]
  diagnostics?: SystemDiagnostics | null
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
  diagnostics = null,
  className = '',
}: CortexActivityProps): ReactElement {
  const { runs, selectedRunId, selectedRun, selectRun, cancelRun, refreshRuns, loading } = runsState

  const residentLocalModel = findResidentLocalModel(agentsStatus)

  return (
    <section
      aria-label="Cortex Activity"
      className={`space-y-4 text-xs font-sans text-zinc-300 ${className}`}
      data-testid="cortex-activity-panel"
    >
      {/* Top Header & Refresh */}
      <div className="flex items-center justify-between border-b border-white/10 pb-2">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-cyan-400" aria-hidden="true" />
          <h3 className="font-mono text-xs uppercase tracking-wider text-zinc-200">
            Cortex Live Activity
          </h3>
          <span className="rounded bg-white/10 px-1.5 py-0.2 font-mono text-[10px] text-zinc-400">
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
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
          {/* Left Column: Recent Runs Selector */}
          <div className="lg:col-span-4 space-y-1.5 max-h-[420px] overflow-y-auto pr-1 scrollbar-thin">
            <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500 px-1 mb-1">
              Recent Runs
            </p>
            {runs.map((run) => {
              const isSelected = run.id === selectedRunId
              return (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => selectRun(run.id)}
                  aria-pressed={isSelected}
                  className={`w-full text-left p-2.5 rounded-lg border transition-colors ${
                    isSelected
                      ? 'border-[#7EB3FF]/50 bg-[#0F4DB8]/15'
                      : 'border-white/5 bg-white/[0.02] hover:border-white/15'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-zinc-300 truncate">
                      {run.resolved_model || run.requested_model}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider ${statusBadgeClass(
                        run.status,
                      )}`}
                    >
                      {statusIcon(run.status)}
                      {run.status}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                    <span>{run.id.slice(0, 8)}…</span>
                    <span>{new Date(run.created_at).toLocaleTimeString()}</span>
                  </div>
                </button>
              )
            })}
          </div>

          {/* Right Column: Selected Run Details */}
          <div className="lg:col-span-8 space-y-3">
            {selectedRun ? (
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3.5 space-y-4">
                {/* Run Summary Header */}
                <div className="flex flex-wrap items-start justify-between gap-2 border-b border-white/10 pb-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wider font-semibold ${statusBadgeClass(
                          selectedRun.status,
                        )}`}
                      >
                        {statusIcon(selectedRun.status)}
                        {selectedRun.status}
                      </span>
                      {selectedRun.stop_reason && (
                        <span className="font-mono text-[11px] text-zinc-400">
                          reason: {selectedRun.stop_reason}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-[10px] text-zinc-500 break-all">
                      Run ID: {selectedRun.id} | Trace: {selectedRun.trace_id || 'none'}
                    </p>
                  </div>

                  {isRunActive(selectedRun.status) && selectedRun.status !== 'cancelling' && (
                    <button
                      type="button"
                      onClick={() => void cancelRun(selectedRun.id)}
                      className="flex items-center gap-1.5 rounded border border-red-500/40 bg-red-950/30 px-2.5 py-1 text-xs font-mono uppercase tracking-wider text-red-300 hover:bg-red-950/50 hover:border-red-500/60 transition-colors"
                      aria-label="Cancel this run"
                    >
                      <Square className="size-3 fill-current" aria-hidden="true" />
                      <span>Stop Run</span>
                    </button>
                  )}
                </div>

                {/* Model & Usage Info */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono">
                  <div className="rounded border border-white/5 bg-black/20 p-2">
                    <span className="text-zinc-500 block text-[10px] uppercase">Model</span>
                    <span className="text-zinc-200 font-semibold truncate block">
                      {selectedRun.resolved_model || selectedRun.requested_model}
                    </span>
                  </div>
                  <div className="rounded border border-white/5 bg-black/20 p-2">
                    <span className="text-zinc-500 block text-[10px] uppercase">Runtime</span>
                    <span className="text-zinc-200 font-semibold">
                      {selectedRun.runtime ?? 'unknown'} ({selectedRun.provider ?? '—'})
                    </span>
                  </div>
                  <div className="rounded border border-white/5 bg-black/20 p-2">
                    <span className="text-zinc-500 block text-[10px] uppercase">Usage Quality</span>
                    <span className="text-zinc-200 font-semibold">{selectedRun.usage_quality}</span>
                  </div>
                  <div className="rounded border border-white/5 bg-black/20 p-2">
                    <span className="text-zinc-500 block text-[10px] uppercase">Total Tokens</span>
                    <span className="text-zinc-200 font-semibold">
                      {selectedRun.total_tokens}
                    </span>
                  </div>
                </div>

                {/* Limit Consumption Gauges */}
                {selectedRun.limit_snapshot && (
                  <div className="space-y-2.5 rounded border border-white/5 bg-black/20 p-3">
                    <h4 className="font-mono text-[10px] uppercase tracking-wider text-zinc-400">
                      Limit Consumption
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                  <div className="space-y-2 rounded border border-white/5 bg-black/20 p-3 font-mono">
                    <h4 className="text-[10px] uppercase tracking-wider text-zinc-400">
                      Runtime Measurements
                    </h4>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[11px]">
                      <div>
                        <span className="text-zinc-500 block text-[10px]">Queue Time</span>
                        <span className="text-zinc-300">{formatDuration(selectedRun.runtime_measurements.queue_duration_ms)}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500 block text-[10px]">TTFT</span>
                        <span className="text-zinc-300">{formatDuration(selectedRun.runtime_measurements.ttft_ms)}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500 block text-[10px]">Eval Duration</span>
                        <span className="text-zinc-300">{formatDuration(selectedRun.runtime_measurements.eval_duration_ms)}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500 block text-[10px]">Total Duration</span>
                        <span className="text-zinc-300">{formatDuration(selectedRun.runtime_measurements.total_duration_ms)}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500 block text-[10px]">Throughput</span>
                        <span className="text-zinc-300">
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
                  <div className="space-y-2 rounded border border-white/5 bg-black/20 p-3 font-mono text-[11px]">
                    <div className="flex items-center justify-between">
                      <h4 className="text-[10px] uppercase tracking-wider text-zinc-400">
                        Execution Evidence
                      </h4>
                      <span className="text-zinc-500 text-[10px]">
                        Tools executed: {Object.values(selectedRun.evidence.tool_outcome_counts ?? {}).reduce((a, b) => a + b, 0)}
                      </span>
                    </div>

                    {Object.keys(selectedRun.evidence.tool_outcome_counts ?? {}).length > 0 ? (
                      <div className="space-y-1">
                        {Object.entries(selectedRun.evidence.tool_outcome_counts).map(([toolName, count]) => (
                          <div
                            key={toolName}
                            className="flex items-center justify-between rounded bg-white/[0.02] px-2 py-1 border border-white/5 text-[10px]"
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
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selectedRun.evidence.action_ids.map((actionId) => (
                            <span
                              key={actionId}
                              className="rounded bg-purple-950/40 border border-purple-500/30 px-1.5 py-0.5 text-[10px] text-purple-300"
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
                  <div className="rounded border border-red-500/30 bg-red-950/20 p-3 text-red-300 text-xs">
                    <p className="font-semibold flex items-center gap-1.5 font-mono text-[11px]">
                      <AlertTriangle className="size-3.5" aria-hidden="true" />
                      Execution Error: ({selectedRun.error.code})
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
        </div>
      )}

      {/* System & Model Residency Summary */}
      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3.5 space-y-3 font-mono">
        <h4 className="text-[10px] uppercase tracking-wider text-zinc-400">
          System & Model Residency
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          {/* Local Model Card */}
          <div className="rounded border border-white/5 bg-black/20 p-2.5">
            <span className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase">
              <Cpu className="size-3 text-cyan-400" aria-hidden="true" />
              Local Model
            </span>
            <span className="mt-1 block font-semibold text-zinc-200 truncate">
              {residentLocalModel ? residentLocalModel.model.model_id : 'None resident'}
            </span>
            {residentLocalModel?.model.idle_unload_remaining_seconds != null && (
              <span className="text-[10px] text-zinc-400 block mt-0.5">
                Idle unload: {residentLocalModel.model.idle_unload_remaining_seconds}s
              </span>
            )}
          </div>

          {/* Host CPU */}
          <div className="rounded border border-white/5 bg-black/20 p-2.5">
            <span className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase">
              <Cpu className="size-3 text-amber-400" aria-hidden="true" />
              CPU Utilization
            </span>
            <span className="mt-1 block font-semibold text-zinc-200 tabular-nums">
              {diagnostics?.cpu != null ? `${diagnostics.cpu.toFixed(1)}%` : '—'}
            </span>
            {diagnostics?.cpu_freq != null && (
              <span className="text-[10px] text-zinc-400 block mt-0.5">
                {(diagnostics.cpu_freq / 1000).toFixed(2)} GHz
              </span>
            )}
          </div>

          {/* Host RAM */}
          <div className="rounded border border-white/5 bg-black/20 p-2.5">
            <span className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase">
              <HardDrive className="size-3 text-purple-400" aria-hidden="true" />
              Host Memory
            </span>
            <span className="mt-1 block font-semibold text-zinc-200 tabular-nums">
              {diagnostics?.ram != null ? `${diagnostics.ram.toFixed(1)}%` : '—'}
            </span>
            {diagnostics?.ram_used != null && diagnostics?.ram_total != null && (
              <span className="text-[10px] text-zinc-400 block mt-0.5">
                {(diagnostics.ram_used / 1024).toFixed(1)} / {(diagnostics.ram_total / 1024).toFixed(1)} GB
              </span>
            )}
          </div>

          {/* Host Disk */}
          <div className="rounded border border-white/5 bg-black/20 p-2.5">
            <span className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase">
              <HardDrive className="size-3 text-emerald-400" aria-hidden="true" />
              Disk Usage
            </span>
            <span className="mt-1 block font-semibold text-zinc-200 tabular-nums">
              {diagnostics?.disk != null ? `${diagnostics.disk.toFixed(1)}%` : '—'}
            </span>
            {diagnostics?.disk_used != null && diagnostics?.disk_total != null && (
              <span className="text-[10px] text-zinc-400 block mt-0.5">
                {diagnostics.disk_used.toFixed(0)} / {diagnostics.disk_total.toFixed(0)} GB
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
