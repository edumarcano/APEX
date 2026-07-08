import { useEffect, useRef, useState } from 'react'
import type { FocusEvent, KeyboardEvent, ReactElement } from 'react'
import {
  Activity,
  Clock,
  Cpu,
  Database,
  Globe,
  HardDrive,
  type LucideIcon,
  RotateCw,
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
    return '--%'
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

function formatGbRatio(
  used: number | null | undefined,
  total: number | null | undefined,
): string {
  if (
    used == null ||
    total == null ||
    !Number.isFinite(used) ||
    !Number.isFinite(total) ||
    total === 0
  ) {
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
  pipelineLabel?: string | null
  failedConnectors?: string[]
  lastBriefingTime?: string | null
}

function MetricBar({
  percentage,
  unavailable,
}: {
  percentage: number
  unavailable: boolean
}): ReactElement {
  return (
    <div className="hud-metric-bar">
      <div
        className={[
          'hud-metric-bar__fill',
          unavailable ? 'bg-zinc-700/60' : getMicroBarColorClass(percentage),
        ].join(' ')}
        style={{ width: `${unavailable ? 18 : percentage}%` }}
      />
    </div>
  )
}

function CompactMetric({
  label,
  value,
  percentage,
  unavailable,
  icon: Icon,
}: {
  label: string
  value: string
  percentage: number
  unavailable: boolean
  icon: LucideIcon
}): ReactElement {
  return (
    <span className="hidden min-w-0 items-center gap-1.5 md:flex">
      <Icon className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
      <span className="w-8 shrink-0 text-zinc-500">{label}</span>
      <span className="w-9 shrink-0 tabular-nums text-zinc-300">{value}</span>
      <span className="w-14 shrink-0">
        <MetricBar percentage={percentage} unavailable={unavailable} />
      </span>
    </span>
  )
}

function DetailMetric({
  label,
  value,
  detail,
  percentage,
  unavailable,
  icon: Icon,
}: {
  label: string
  value: string
  detail: string
  percentage: number
  unavailable: boolean
  icon: LucideIcon
}): ReactElement {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-zinc-500">
          <Icon className="size-3.5 shrink-0" aria-hidden />
          {label}
        </span>
        <span className="tabular-nums text-zinc-300">{value}</span>
      </div>
      <MetricBar percentage={percentage} unavailable={unavailable} />
      <p className="mt-1 truncate text-[10px] text-zinc-600">{detail}</p>
    </div>
  )
}

export function SystemDiagnostics({
  diagnostics,
  diagnosticsStatus,
  isSpeaking,
  isPipelinePolling,
  status,
  confidenceScore,
  pipelineStep,
  pipelineLabel = null,
  failedConnectors = [],
  lastBriefingTime = null,
}: SystemDiagnosticsProps): ReactElement {
  const [isBrowserOnline, setIsBrowserOnline] = useState(navigator.onLine)
  const [isOpen, setIsOpen] = useState(false)
  const [isPinned, setIsPinned] = useState(false)
  const [liveTime, setLiveTime] = useState({ date: '', time: '' })
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const updateClock = (): void => {
      const now = new Date()
      const dateStr = now.toLocaleDateString('en-US', {
        weekday: 'short',
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
    const handleOnline = (): void => setIsBrowserOnline(true)
    const handleOffline = (): void => setIsBrowserOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

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

  const handleTriggerKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleToggleClick()
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      setIsPinned(false)
      setIsOpen(false)
    }
  }

  const handleBlur = (event: FocusEvent<HTMLDivElement>): void => {
    const nextTarget = event.relatedTarget
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return
    }
    if (!isPinned) {
      setIsOpen(false)
    }
  }

  const isInitializing = diagnosticsStatus === 'idle' || diagnosticsStatus === 'loading'
  const isNetworkConnected = isBrowserOnline && diagnosticsStatus !== 'error'

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

  const displayPipelineText = pipelineLabel?.trim() || briefingStateText

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

  const activeBlocksCount = Math.max(0, Math.min(10, Math.floor((confidenceScore ?? 0) / 10)))
  const syncBlocks = Array.from({ length: 10 }, (_, i) => {
    const isSuccess = status === 'success'
    const isActive = isSuccess && i < activeBlocksCount
    return (
      <div
        key={i}
        className={`w-1 rounded-sm transition-colors duration-500 ${EQUALIZER_HEIGHTS[i]} ${
          isSuccess
            ? isActive
              ? `${syncColorBar} ${syncColorShadow}`
              : 'bg-zinc-700'
            : 'bg-zinc-800/60'
        }`}
      />
    )
  })

  const cpuUnavailable = isMetricUnavailable(diagnostics.cpu, isInitializing)
  const cpuPctClamped = cpuUnavailable ? 0 : clampPercentage(diagnostics.cpu ?? 0)
  const ramUnavailable = isMetricUnavailable(diagnostics.ram, isInitializing)
  const ramPctClamped = ramUnavailable ? 0 : clampPercentage(diagnostics.ram ?? 0)
  const diskUnavailable = isMetricUnavailable(diagnostics.disk, isInitializing)
  const diskPctClamped = diskUnavailable ? 0 : clampPercentage(diagnostics.disk ?? 0)

  const cpuText = formatPercentage(diagnostics.cpu, isInitializing)
  const ramText = formatPercentage(diagnostics.ram, isInitializing)
  const diskText = formatPercentage(diagnostics.disk, isInitializing)

  return (
    <div
      ref={containerRef}
      className="relative h-16 w-40 shrink-0 pointer-events-auto sm:w-[min(66vw,44rem)]"
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => {
        if (!isPinned) setIsOpen(false)
      }}
      onBlur={handleBlur}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={handleToggleClick}
        onKeyDown={handleTriggerKeyDown}
        className={`hud-corner-brackets hud-interactive-shell hud-glass absolute right-0 top-1/2 flex h-11 w-[min(100%,31rem)] -translate-y-1/2 cursor-pointer items-center gap-3 overflow-hidden rounded-full px-4 font-mono text-xs text-zinc-300 transition-all duration-300 hover-blue-medium ${
          isOpen ? 'pointer-events-none translate-x-3 opacity-0' : 'opacity-100'
        }`}
        aria-expanded={isOpen}
        aria-label="System diagnostics"
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
        <span className="hud-inner-lift flex min-w-0 flex-1 items-center gap-3">
          <span className={`hud-led size-1.5 ${briefingLedClass}`} aria-hidden title={displayPipelineText} />
          <span className="min-w-0 flex-1 truncate uppercase tracking-[0.16em] text-zinc-300">
            {displayPipelineText}
          </span>
          <CompactMetric
            label="CPU"
            value={cpuText}
            percentage={cpuPctClamped}
            unavailable={cpuUnavailable}
            icon={Cpu}
          />
          <CompactMetric
            label="RAM"
            value={ramText}
            percentage={ramPctClamped}
            unavailable={ramUnavailable}
            icon={Database}
          />
          <span className="hidden items-center gap-1 sm:flex">
            <Clock className="size-3.5 text-zinc-500" aria-hidden />
            <span className="tabular-nums whitespace-nowrap">{liveTime.time}</span>
          </span>
        </span>
      </div>

      <div
        className={`hud-corner-brackets hud-glass hud-glass-solid absolute right-0 top-0 z-50 flex h-16 w-full min-w-0 origin-right items-center gap-4 overflow-hidden rounded-2xl border border-white/10 px-4 shadow-2xl transition-all duration-300 ${
          isOpen ? 'pointer-events-auto translate-x-0 opacity-100' : 'pointer-events-none translate-x-4 opacity-0'
        }`}
        role="dialog"
        aria-label="Full system diagnostics"
        aria-hidden={!isOpen}
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />

        <div className="flex min-w-[9rem] flex-col gap-1 font-mono">
          <p className="truncate text-[9px] font-extrabold uppercase tracking-[0.24em] text-[#7EB3FF]">
            System Status
          </p>
          <div className="flex min-w-0 items-center gap-2 text-xs text-zinc-300">
            <span className={`hud-led size-1.5 ${briefingLedClass}`} aria-hidden />
            <span className="truncate">{displayPipelineText}</span>
          </div>
        </div>

        <div className="hidden min-w-[8rem] grid-cols-1 gap-1.5 font-mono text-[10px] text-zinc-300 sm:grid">
          <span className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-zinc-500">
              <Globe className="size-3.5" aria-hidden />
              Net
            </span>
            <span className="flex items-center gap-1.5">
              <span className={`hud-led size-1.5 ${isNetworkConnected ? 'hud-led--live' : 'hud-led--error'}`} aria-hidden />
              {isNetworkConnected ? 'Online' : 'Offline'}
            </span>
          </span>
          <span className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-zinc-500">
              <Activity className="size-3.5" aria-hidden />
              Last
            </span>
            <span className="truncate text-zinc-300">{lastBriefingTime || 'Standby'}</span>
          </span>
        </div>

        <div className="grid min-w-0 flex-1 grid-cols-2 gap-3 lg:grid-cols-3">
          <DetailMetric
            label="CPU"
            value={cpuText}
            detail={formatCpuFreq(diagnostics.cpu_freq)}
            percentage={cpuPctClamped}
            unavailable={cpuUnavailable}
            icon={Cpu}
          />
          <DetailMetric
            label="RAM"
            value={ramText}
            detail={formatGbRatio(diagnostics.ram_used, diagnostics.ram_total)}
            percentage={ramPctClamped}
            unavailable={ramUnavailable}
            icon={Database}
          />
          <div className="hidden lg:block">
            <DetailMetric
              label="Disk"
              value={diskText}
              detail={formatGbRatio(diagnostics.disk_used, diagnostics.disk_total)}
              percentage={diskPctClamped}
              unavailable={diskUnavailable}
              icon={HardDrive}
            />
          </div>
        </div>

        <div className="hidden w-28 shrink-0 flex-col gap-1 font-mono md:flex">
          <div className="flex items-center justify-between gap-2 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1.5">
              <RotateCw className="size-3.5 animate-[spin_12s_linear_infinite]" aria-hidden />
              Sync
            </span>
            <span className={`${syncColorText} font-bold`}>
              {status === 'success' ? `${confidenceScore}%` : '--%'}
            </span>
          </div>
          <div className="flex items-center gap-0.5">{syncBlocks}</div>
          <p className="truncate text-[9px] text-amber-300/80">
            {failedConnectors.length > 0
              ? failedConnectors.map(formatConnectorLabel).join(', ')
              : `${liveTime.date} ${liveTime.time}`}
          </p>
        </div>
      </div>
    </div>
  )
}
