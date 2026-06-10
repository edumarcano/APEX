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

function getMicroBarColorClass(percentage: number): string {
  if (percentage >= 90) {
    return 'bg-[#ef4444] drop-shadow-[0_0_4px_rgba(239,68,68,0.5)]'
  }
  if (percentage >= 80) {
    return 'bg-[#f59e0b] drop-shadow-[0_0_4px_rgba(245,158,11,0.5)]'
  }
  return 'bg-[#3b82f6] drop-shadow-[0_0_4px_rgba(59,130,246,0.3)]'
}

interface SystemDiagnosticsProps {
  diagnosticsStatus: 'idle' | 'loading' | 'ready' | 'error'
  isSpeaking: boolean
  isPipelinePolling: boolean
  status: 'idle' | 'loading' | 'success' | 'error'
  confidenceScore: number
  lastBriefingTime: string | null
  pipelineStep: number | null
}

export function SystemDiagnostics({
  diagnosticsStatus,
  isSpeaking,
  isPipelinePolling,
  status,
  confidenceScore,
  lastBriefingTime,
  pipelineStep,
}: SystemDiagnosticsProps): ReactElement {
  const { diagnostics, status: localStatus } = useSystemDiagnostics()
  const resolvedDiagnostics = diagnostics ?? DEFAULT_SYSTEM_DIAGNOSTICS
  const isInitializing = localStatus === 'idle' || localStatus === 'loading'

  // Segment 2 (Briefing Status) State Resolution
  let briefingStateText: string
  let briefingDot: ReactElement

  if (status === 'error') {
    briefingStateText = 'Fault'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
    )
  } else if (
    isPipelinePolling &&
    pipelineStep !== null &&
    pipelineStep >= 1 &&
    pipelineStep <= 3
  ) {
    briefingStateText = 'Processing'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse" />
    )
  } else if (pipelineStep === 4 || isSpeaking) {
    briefingStateText = 'Delivering'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.8)] animate-gold-glow" />
    )
  } else if (status === 'success' && !isSpeaking) {
    briefingStateText = 'Complete'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
    )
  } else {
    briefingStateText = 'Standby'
    briefingDot = (
      <span className="h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
    )
  }

  // Segment 3: Sync Health Vertical Blocks
  const activeBlocksCount = Math.floor((confidenceScore ?? 0) / 10)
  const syncBlocks = Array.from({ length: 10 }, (_, i) => {
    const isSuccess = status === 'success'
    const isActive = isSuccess && i < activeBlocksCount
    return (
      <div
        key={i}
        className={`h-3 w-1 rounded-sm transition-colors duration-500 ${
          isSuccess
            ? isActive
              ? 'bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]'
              : 'bg-zinc-700'
            : 'bg-zinc-800/40'
        }`}
      />
    )
  })

  // Hardware Resource Clamped Percentages
  const cpuVal = resolvedDiagnostics.cpu ?? 0
  const cpuUnavailable = isMetricUnavailable(resolvedDiagnostics.cpu, isInitializing)
  const cpuPctClamped = cpuUnavailable ? 0 : clampPercentage(cpuVal)

  const ramVal = resolvedDiagnostics.ram ?? 0
  const ramUnavailable = isMetricUnavailable(resolvedDiagnostics.ram, isInitializing)
  const ramPctClamped = ramUnavailable ? 0 : clampPercentage(ramVal)

  const diskVal = resolvedDiagnostics.disk ?? 0
  const diskUnavailable = isMetricUnavailable(resolvedDiagnostics.disk, isInitializing)
  const diskPctClamped = diskUnavailable ? 0 : clampPercentage(diskVal)

  return (
    <footer className="w-full border border-white/5 bg-zinc-950/40 backdrop-blur-md rounded-xl p-4 mt-auto z-40 select-none">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-6 items-center justify-between text-xs font-mono text-zinc-400 font-medium">
        
        {/* Column 1: Title */}
        <div className="flex items-center">
          <span className="text-[#0F4DB8] font-extrabold tracking-wider uppercase text-xs">
            SYSTEM STATUS
          </span>
        </div>

        {/* Column 2: Internet Connection */}
        <div className="flex items-center gap-3">
          <Globe className="h-4 w-4 text-zinc-400 shrink-0" />
          <div className="flex flex-col">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500">
              Internet
            </span>
            <span className="flex items-center gap-1.5 mt-0.5 text-zinc-300">
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

        {/* Column 3: Briefing Status */}
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

        {/* Column 4: Sync Health */}
        <div className="flex items-center gap-3">
          <RotateCw className="h-4 w-4 text-zinc-400 shrink-0 animate-[spin_12s_linear_infinite]" />
          <div className="flex flex-col gap-1 w-full max-w-[120px]">
            <span className="text-[10px] tracking-wider uppercase text-zinc-500 flex justify-between">
              <span>Sync Health</span>
              {status === 'success' ? (
                <span className="text-emerald-400 font-bold">{confidenceScore}%</span>
              ) : (
                <span className="text-zinc-500 font-bold">—%</span>
              )}
            </span>
            <div className="flex items-center gap-0.5">{syncBlocks}</div>
          </div>
        </div>

        {/* Column 5: Hardware Resources */}
        <div className="flex items-center gap-4 flex-wrap sm:flex-nowrap">
          {/* CPU */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1 text-[11px] text-zinc-300">
              <Cpu className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
              <span>CPU {formatPercentage(resolvedDiagnostics.cpu, isInitializing)}</span>
            </div>
            <div className="w-12 h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(cpuPctClamped)}`}
                style={{ width: `${cpuPctClamped}%` }}
              />
            </div>
          </div>

          {/* RAM */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1 text-[11px] text-zinc-300">
              <Database className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
              <span>RAM {formatPercentage(resolvedDiagnostics.ram, isInitializing)}</span>
            </div>
            <div className="w-12 h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(ramPctClamped)}`}
                style={{ width: `${ramPctClamped}%` }}
              />
            </div>
          </div>

          {/* DISK */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1 text-[11px] text-zinc-300">
              <HardDrive className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
              <span>DISK {formatPercentage(resolvedDiagnostics.disk, isInitializing)}</span>
            </div>
            <div className="w-12 h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(diskPctClamped)}`}
                style={{ width: `${diskPctClamped}%` }}
              />
            </div>
          </div>
        </div>

        {/* Column 6: Last Briefing */}
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
