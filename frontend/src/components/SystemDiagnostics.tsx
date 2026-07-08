import { useState, useEffect, useRef } from 'react'
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

import {
  type SystemDiagnostics as SystemDiagnosticsPayload,
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

const CONNECTOR_LABELS: Record<string, string> = {
  weather: 'Weather',
  news: 'News',
  email: 'Email',
  calendar: 'Calendar',
  sports: 'Sports (F1)',
  sports_f1: 'Formula 1',
  sports_football: 'Barcelona Football',
}

function formatConnectorLabel(connectorId: string): string {
  const normalized = connectorId.trim().toLowerCase()
  return CONNECTOR_LABELS[normalized] ?? connectorId
}

function formatCpuFreq(freq: number | null | undefined): string {
  if (freq == null || !Number.isFinite(freq) || freq === 0) {
    return 'N/A'
  }
  return `${freq.toFixed(1)} GHz`
}

function formatGbRatio(used: number | null | undefined, total: number | null | undefined): string {
  if (used == null || total == null || !Number.isFinite(used) || !Number.isFinite(total) || total === 0) {
    return 'N/A'
  }
  return `${used.toFixed(1)} / ${total.toFixed(1)} GB`
}

function getMicroBarColorClass(percentage: number): string {
  if (percentage >= 90) {
    return 'bg-gradient-to-r from-red-600 to-red-400 shadow-[0_0_8px_rgba(239,68,68,0.8)]'
  }
  if (percentage >= 80) {
    return 'bg-gradient-to-r from-amber-600 to-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.8)]'
  }
  return 'bg-gradient-to-r from-blue-600 to-blue-400 shadow-[0_0_8px_rgba(59,130,246,0.8)]'
}

const EQUALIZER_HEIGHTS: readonly string[] = [
  'h-[6px]',
  'h-[10px]',
  'h-[14px]',
  'h-[18px]',
  'h-[22px]',
  'h-[22px]',
  'h-[18px]',
  'h-[14px]',
  'h-[10px]',
  'h-[6px]',
]

interface SystemDiagnosticsProps {
  diagnostics: SystemDiagnosticsPayload
  diagnosticsStatus: 'idle' | 'loading' | 'ready' | 'error'
  isSpeaking: boolean
  isPipelinePolling: boolean
  status: 'idle' | 'loading' | 'success' | 'error'
  confidenceScore: number
  pipelineStep: number | null
  failedConnectors?: string[]
}

/**
 * Compact header pill surfacing the three signals that matter at a glance
 * (briefing status, CPU, RAM), expanding into a full detail dropdown on
 * hover or click (internet, sync/confidence, disk, live clock).
 */
export function SystemDiagnostics({
  diagnostics,
  diagnosticsStatus,
  isSpeaking,
  isPipelinePolling,
  status,
  confidenceScore,
  pipelineStep,
  failedConnectors = [],
}: SystemDiagnosticsProps): ReactElement {
  const [isBrowserOnline, setIsBrowserOnline] = useState(navigator.onLine)
  const [isOpen, setIsOpen] = useState(false)
  const [isPinned, setIsPinned] = useState(false)
  const [liveTime, setLiveTime] = useState({ date: '', time: '' })
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const updateClock = () => {
      const now = new Date()
      const dateStr = now.toLocaleDateString('en-US', {
        weekday: 'long',
        month: 'short',
        day: '2-digit',
      })
      const timeStr = now.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      })
      setLiveTime({ date: dateStr, time: timeStr })
    }

    updateClock()
    const timerId = setInterval(updateClock, 1000)
    return () => clearInterval(timerId)
  }, [])

  useEffect(() => {
    const handleOnline = () => setIsBrowserOnline(true)
    const handleOffline = () => setIsBrowserOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Close the pinned dropdown on outside click (touch/accessibility path).
  useEffect(() => {
    if (!isPinned) return

    const handleOutsideClick = (event: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsPinned(false)
        setIsOpen(false)
      }
    }

    window.addEventListener('mousedown', handleOutsideClick)
    return () => {
      window.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [isPinned])

  const handleToggleClick = (): void => {
    setIsPinned((prev) => {
      const next = !prev
      setIsOpen(next)
      return next
    })
  }

  const resolvedDiagnostics = diagnostics
  const isInitializing = diagnosticsStatus === 'idle' || diagnosticsStatus === 'loading'

  const isNetworkConnected = isBrowserOnline && diagnosticsStatus !== 'error'

  // Segment: Briefing Status resolution
  let briefingStateText: string
  let briefingLedClass: string

  if (status === 'error') {
    briefingStateText = 'Fault'
    briefingLedClass = 'hud-led--error'
  } else if (isPipelinePolling && (pipelineStep === 1 || pipelineStep === 2)) {
    briefingStateText = 'Collecting Data'
    briefingLedClass = 'hud-led--live'
  } else if (isPipelinePolling && pipelineStep === 3) {
    briefingStateText = 'Synthesizing'
    briefingLedClass = 'hud-led--live'
  } else if (pipelineStep === 4 || isSpeaking) {
    briefingStateText = 'Delivering'
    briefingLedClass = 'hud-led--stale'
  } else if (status === 'success' && !isSpeaking) {
    briefingStateText = 'Complete'
    briefingLedClass = 'hud-led--live'
  } else {
    briefingStateText = 'Standby'
    briefingLedClass = 'hud-led--loading'
  }

  // Segment: Sync Health dynamic 3-tier adaptive color schemes
  let syncColorText = 'text-zinc-500'
  let syncColorBar = 'bg-zinc-700'
  let syncColorShadow = ''

  if (status === 'success') {
    if (confidenceScore >= 90) {
      syncColorText = 'text-emerald-400'
      syncColorBar = 'bg-emerald-500'
      syncColorShadow = 'shadow-[0_0_4px_rgba(16,185,129,0.5)]'
    } else if (confidenceScore >= 50) {
      syncColorText = 'text-amber-400'
      syncColorBar = 'bg-amber-500'
      syncColorShadow = 'shadow-[0_0_4px_rgba(245,158,11,0.5)]'
    } else {
      syncColorText = 'text-red-400'
      syncColorBar = 'bg-red-500'
      syncColorShadow = 'shadow-[0_0_4px_rgba(239,68,68,0.5)]'
    }
  }

  const activeBlocksCount = Math.floor((confidenceScore ?? 0) / 10)
  const syncBlocks = Array.from({ length: 10 }, (_, i) => {
    const isSuccess = status === 'success'
    const isActive = isSuccess && i < activeBlocksCount
    return (
      <div
        key={i}
        className={`w-1 rounded-sm transition-colors duration-500 ${EQUALIZER_HEIGHTS[i]} ${isSuccess
          ? isActive
            ? `${syncColorBar} ${syncColorShadow}`
            : 'bg-zinc-700'
          : 'bg-zinc-800/40'
          }`}
      />
    )
  })

  // Hardware resource clamped percentages
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
    <div
      ref={containerRef}
      className="relative shrink-0 pointer-events-auto"
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => {
        if (!isPinned) setIsOpen(false)
      }}
    >
      {/* Compact trigger pill — CPU / RAM / Briefing status only */}
      <button
        type="button"
        onClick={handleToggleClick}
        className="hud-corner-brackets hud-glass relative flex h-11 shrink-0 items-center gap-2.5 rounded-full px-3 font-mono text-xs text-zinc-300 transition-all duration-500 hover-blue-medium"
        aria-expanded={isOpen}
        aria-label="System diagnostics"
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />

        <span className={`hud-led size-1.5 ${briefingLedClass}`} aria-hidden title={briefingStateText} />

        <span className="hidden items-center gap-1 sm:flex">
          <Cpu className="size-3.5 text-zinc-500" aria-hidden />
          <span>{formatPercentage(resolvedDiagnostics.cpu, isInitializing)}</span>
        </span>

        <span className="flex items-center gap-1">
          <Database className="size-3.5 text-zinc-500" aria-hidden />
          <span>{formatPercentage(resolvedDiagnostics.ram, isInitializing)}</span>
        </span>
      </button>

      {/* Expanded detail dropdown */}
      <div
        className={`hud-corner-brackets hud-glass absolute right-0 top-full z-50 mt-2 w-72 origin-top-right rounded-2xl border border-white/10 p-4 shadow-2xl transition-all duration-300 ${
          isOpen ? 'pointer-events-auto scale-100 opacity-100' : 'pointer-events-none scale-95 opacity-0'
        }`}
        role="dialog"
        aria-label="Full system diagnostics"
        aria-hidden={!isOpen}
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />

        <p className="mb-3 font-mono text-[10px] font-extrabold uppercase tracking-wider text-[#0F4DB8]">
          System Status
        </p>

        <div className="space-y-3 font-mono text-xs text-zinc-300">
          {/* Internet */}
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-zinc-500">
              <Globe className="size-3.5 shrink-0" aria-hidden />
              Internet
            </span>
            <span className="flex items-center gap-1.5">
              <span className={`hud-led size-1.5 ${isNetworkConnected ? 'hud-led--live' : 'hud-led--error'}`} aria-hidden />
              {isNetworkConnected ? 'Connected' : 'Offline'}
            </span>
          </div>

          {/* Briefing */}
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-zinc-500">
              <Activity className="size-3.5 shrink-0" aria-hidden />
              Briefing
            </span>
            <span className="flex items-center gap-1.5">
              <span className={`hud-led size-1.5 ${briefingLedClass}`} aria-hidden />
              {briefingStateText}
            </span>
          </div>

          {/* Sync / Confidence */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-zinc-500">
                <RotateCw className="size-3.5 shrink-0 animate-[spin_12s_linear_infinite]" aria-hidden />
                Sync
              </span>
              {status === 'success' ? (
                <span className={`${syncColorText} font-bold`}>{confidenceScore}%</span>
              ) : (
                <span className="font-bold text-zinc-500">—%</span>
              )}
            </div>
            <div className="mt-1.5 flex items-center gap-0.5">{syncBlocks}</div>
            {failedConnectors.length > 0 ? (
              <ul className="mt-1.5 space-y-0.5 text-[10px] text-amber-300/90">
                {failedConnectors.map((connectorId) => (
                  <li key={connectorId}>{formatConnectorLabel(connectorId)} unavailable</li>
                ))}
              </ul>
            ) : null}
          </div>

          <div className="hud-header-divider" aria-hidden />

          {/* CPU */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-zinc-500">
                <Cpu className="size-3.5 shrink-0" aria-hidden />
                CPU
              </span>
              <span>{formatPercentage(resolvedDiagnostics.cpu, isInitializing)} · {formatCpuFreq(resolvedDiagnostics.cpu_freq)}</span>
            </div>
            <div className="relative mt-1.5 h-2 overflow-hidden rounded-full border border-white/5 bg-black/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.6)]">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(cpuPctClamped)}`}
                style={{ width: `${cpuPctClamped}%` }}
              />
            </div>
          </div>

          {/* RAM */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-zinc-500">
                <Database className="size-3.5 shrink-0" aria-hidden />
                RAM
              </span>
              <span>{formatGbRatio(resolvedDiagnostics.ram_used, resolvedDiagnostics.ram_total)}</span>
            </div>
            <div className="relative mt-1.5 h-2 overflow-hidden rounded-full border border-white/5 bg-black/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.6)]">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(ramPctClamped)}`}
                style={{ width: `${ramPctClamped}%` }}
              />
            </div>
          </div>

          {/* DISK */}
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-zinc-500">
                <HardDrive className="size-3.5 shrink-0" aria-hidden />
                Disk
              </span>
              <span>{formatGbRatio(resolvedDiagnostics.disk_used, resolvedDiagnostics.disk_total)}</span>
            </div>
            <div className="relative mt-1.5 h-2 overflow-hidden rounded-full border border-white/5 bg-black/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.6)]">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-in-out ${getMicroBarColorClass(diskPctClamped)}`}
                style={{ width: `${diskPctClamped}%` }}
              />
            </div>
          </div>

          <div className="hud-header-divider" aria-hidden />

          {/* Time */}
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-zinc-500">
              <Clock className="size-3.5 shrink-0" aria-hidden />
              Time
            </span>
            <span className="tabular-nums text-zinc-300">
              {liveTime.date} · {liveTime.time}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
