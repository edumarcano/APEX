import type { ReactElement } from 'react'
import {
  Globe,
  Activity,
  RotateCw,
  Cpu,
  Database,
  HardDrive,
  Clock,
} from 'lucide-react'

import { useSystemDiagnostics } from '../hooks/useSystemDiagnostics'
import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
} from '../types/telemetry'

function clampPercentage(value: number): number {
  return Math.min(100, Math.max(0, value))
}

function isMetricUnavailable(
  value: number | null | undefined,
  isInitializing: boolean,
): boolean {
  return isInitializing || value == null || !Number.isFinite(value)
}

function formatPercentage(
  value: number | null | undefined,
  isInitializing: boolean,
): string {
  if (isMetricUnavailable(value, isInitializing)) {
    return '—%'
  }
  return `${Math.round(clampPercentage(value!))}%`
}

interface SystemDiagnosticsProps {
  diagnosticsStatus: 'idle' | 'loading' | 'ready' | 'error'
  isSpeaking: boolean
  isPipelinePolling: boolean
  status: 'idle' | 'loading' | 'success' | 'error'
  confidenceScore: number
  lastBriefingTime: string | null
}

export function SystemDiagnostics({
  diagnosticsStatus,
  isSpeaking,
  isPipelinePolling,
  status,
  confidenceScore,
  lastBriefingTime,
}: SystemDiagnosticsProps): ReactElement {
  const { diagnostics, status: localStatus } = useSystemDiagnostics()
  const resolvedDiagnostics = diagnostics ?? DEFAULT_SYSTEM_DIAGNOSTICS
  const isInitializing = localStatus === 'idle' || localStatus === 'loading'

  // Segment 2 (Briefing Status) State Resolution
  let briefingStateText = 'Standby'
  let briefingDot = (
    <span className="h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
  )

  if (isSpeaking) {
    briefingStateText = 'Delivering'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.8)] animate-pulse" />
    )
  } else if (isPipelinePolling) {
    briefingStateText = 'Processing'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-[pulse_1s_infinite]" />
    )
  } else if (status === 'success') {
    briefingStateText = 'Ready'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
    )
  } else if (status === 'idle') {
    briefingStateText = 'Standby'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
    )
  }

  // Segment 3: Sync Health Vertical Blocks
  const activeBlocksCount = Math.floor((confidenceScore ?? 0) / 10)
  const syncBlocks = Array.from({ length: 10 }, (_, i) => {
    const isActive = i < activeBlocksCount
    return (
      <div
        key={i}
        className={`h-3 w-1 rounded-sm transition-colors duration-500 ${
          isActive
            ? 'bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]'
            : 'bg-zinc-700'
        }`}
      />
    )
  })

  return (
    <footer className="w-full border border-white/5 bg-zinc-950/40 backdrop-blur-md rounded-xl p-4 mt-auto z-40 select-none">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-6 items-center justify-between text-xs font-mono text-zinc-400 font-medium">
        {/* Segment 1: Connection & Internet Status */}
        <div className="flex items-center gap-3">
          <Globe className="h-4 w-4 text-cyan-400 shrink-0" />
          <div className="flex flex-col">
            <span className="text-[10px] tracking-wider uppercase text-cyan-400 font-bold">
              SYSTEM STATUS
            </span>
            <span className="flex items-center gap-1.5 mt-0.5 text-zinc-300">
              Internet:{' '}
              {diagnosticsStatus === 'ready' ? (
                <>
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
                  <span className="text-zinc-200">Connected</span>
                </>
              ) : (
                <>
                  <span className="h-1.5 w-1.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
                  <span className="text-zinc-400">Offline</span>
                </>
              )}
            </span>
          </div>
        </div>

        {/* Segment 2: Briefing Status */}
        <div className="flex items-center gap-3">
          <Activity className="h-4 w-4 text-zinc-400 shrink-0" />
          <div className="flex flex-col">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500">
              Briefing Status
            </span>
            <span className="flex items-center gap-1.5 mt-0.5 text-zinc-300">
              {briefingDot}
              <span>{briefingStateText}</span>
            </span>
          </div>
        </div>

        {/* Segment 3: Sync Health */}
        <div className="flex items-center gap-3">
          <RotateCw className="h-4 w-4 text-zinc-400 shrink-0 animate-[spin_12s_linear_infinite]" />
          <div className="flex flex-col gap-1 w-full max-w-[120px]">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500 flex justify-between">
              <span>Sync Health</span>
              <span className="text-emerald-400 font-bold">{confidenceScore}%</span>
            </span>
            <div className="flex items-center gap-0.5">{syncBlocks}</div>
          </div>
        </div>

        {/* Segment 4: Compact Hardware resource gauges */}
        <div className="flex items-center gap-3 col-span-1">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500">
              Resources
            </span>
            <div className="flex items-center gap-3.5 text-zinc-300">
              <div className="flex items-center gap-1">
                <Cpu className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
                <span>CPU {formatPercentage(resolvedDiagnostics.cpu, isInitializing)}</span>
              </div>
              <div className="flex items-center gap-1">
                <Database className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
                <span>RAM {formatPercentage(resolvedDiagnostics.ram, isInitializing)}</span>
              </div>
              <div className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
                <span>DISK {formatPercentage(resolvedDiagnostics.disk, isInitializing)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Segment 5: Last Briefing */}
        <div className="flex items-center gap-3">
          <Clock className="h-4 w-4 text-zinc-400 shrink-0" />
          <div className="flex flex-col">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500">
              Last Briefing
            </span>
            <span className="text-zinc-200 mt-0.5">
              {lastBriefingTime ?? 'Standby'}
            </span>
          </div>
        </div>
      </div>
    </footer>
  )
}
