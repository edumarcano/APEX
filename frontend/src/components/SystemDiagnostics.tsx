import { useEffect, useRef, useState } from 'react'
import type { FocusEvent, KeyboardEvent, ReactElement, RefObject } from 'react'
import {
  Clock,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Settings,
  type LucideIcon,
  RotateCw,
} from 'lucide-react'

import {
  type AgentProfileStatus,
  type ConnectorHealthEntry,
  type SystemDiagnostics as SystemDiagnosticsPayload,
} from '../types/telemetry'
import type { BriefingMode } from '../types/settings'
import { BriefingModeSelector } from './BriefingControls'

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
  sports: 'Sports',
  f1: 'Formula 1',
  football: 'Barcelona Football',
  sports_f1: 'Formula 1',
  sports_football: 'Barcelona Football',
  reminders: 'Reminders',
}

function formatConnectorLabel(connectorId: string): string {
  const normalized = connectorId.trim().toLowerCase()
  return CONNECTOR_LABELS[normalized] ?? connectorId
}

function formatHealthSummary(
  connectorHealth: ConnectorHealthEntry[],
  failedConnectors: string[],
): { hasIssues: boolean; text: string } {
  if (connectorHealth.length > 0) {
    const degraded = connectorHealth.filter((entry) => entry.status === 'degraded')
    const unavailable = connectorHealth.filter((entry) => entry.status === 'unavailable')
    if (unavailable.length === 0 && degraded.length === 0) {
      return { hasIssues: false, text: 'All connectors clear' }
    }
    const parts = [
      ...unavailable.map((entry) => `${formatConnectorLabel(entry.name)} unavailable`),
      ...degraded.map((entry) => `${formatConnectorLabel(entry.name)} degraded`),
    ]
    return { hasIssues: true, text: parts.join(', ') }
  }
  if (failedConnectors.length > 0) {
    return {
      hasIssues: true,
      text: failedConnectors.map(formatConnectorLabel).join(', '),
    }
  }
  return { hasIssues: false, text: 'All connectors clear' }
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
  status: 'idle' | 'loading' | 'success' | 'error'
  confidenceScore: number
  failedConnectors?: string[]
  connectorHealth?: ConnectorHealthEntry[]
  demoModeActive?: boolean
  devModeActive?: boolean
  briefingMode: BriefingMode
  onBriefingModeChange: (mode: BriefingMode) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  briefingControlsBusy: boolean
  onOpenSettings?: () => void
  settingsButtonRef?: RefObject<HTMLButtonElement | null>
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

function MetricPill({
  label,
  value,
  percentage,
  unavailable,
  icon: Icon,
  className = '',
}: {
  label: string
  value: string
  percentage: number
  unavailable: boolean
  icon: LucideIcon
  className?: string
}): ReactElement {
  return (
    <div
      className={`hud-interactive-shell hud-glass flex h-11 items-center gap-2 rounded-full px-3 font-mono text-xs text-zinc-300 ${className}`}
    >
      <span className="hud-inner-lift flex min-w-0 items-center gap-2">
        <Icon className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
        <span className="shrink-0 text-[9px] uppercase tracking-[0.16em] text-zinc-500">
          {label}
        </span>
        <span className="shrink-0 tabular-nums text-[10px] text-zinc-300">{value}</span>
        <span className="w-10 shrink-0 sm:w-12">
          <MetricBar percentage={percentage} unavailable={unavailable} />
        </span>
      </span>
    </div>
  )
}

function StatusPill({
  label,
  value,
  ledClass,
  icon: Icon,
  className = '',
}: {
  label: string
  value: string
  ledClass: string
  icon: LucideIcon
  className?: string
}): ReactElement {
  return (
    <div
      className={`hud-interactive-shell hud-glass flex h-11 items-center gap-2 rounded-full px-3 font-mono text-xs text-zinc-300 ${className}`}
    >
      <span className="hud-inner-lift flex min-w-0 items-center gap-2">
        <Icon className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
        <span className="shrink-0 text-[9px] uppercase tracking-[0.16em] text-zinc-500">
          {label}
        </span>
        <span className={`hud-led size-1.5 ${ledClass}`} aria-hidden />
        <span className="shrink-0 tabular-nums text-[10px] uppercase tracking-[0.12em] text-zinc-300">
          {value}
        </span>
      </span>
    </div>
  )
}

function ClockPill({ time }: { time: string }): ReactElement {
  return (
    <div className="hud-interactive-shell hud-glass flex h-11 items-center gap-2 rounded-full px-3 font-mono text-xs text-zinc-300">
      <span className="hud-inner-lift flex min-w-0 items-center gap-2">
        <Clock className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
        <span className="tabular-nums whitespace-nowrap text-[10px] text-zinc-300">{time}</span>
      </span>
    </div>
  )
}

export function SystemDiagnostics({
  diagnostics,
  diagnosticsStatus,
  status,
  confidenceScore,
  failedConnectors = [],
  connectorHealth = [],
  demoModeActive = false,
  devModeActive = false,
  briefingMode,
  onBriefingModeChange,
  profilesStatus,
  profilesStatusHydrated,
  briefingControlsBusy,
  onOpenSettings,
  settingsButtonRef,
}: SystemDiagnosticsProps): ReactElement {
  const [isBrowserOnline, setIsBrowserOnline] = useState(navigator.onLine)
  const [isOpen, setIsOpen] = useState(false)
  const [isPinned, setIsPinned] = useState(false)
  const [liveTime, setLiveTime] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  const healthSummary = formatHealthSummary(connectorHealth, failedConnectors)
  const hasConnectorFailures = healthSummary.hasIssues
  const modeSubtitle = demoModeActive ? 'DEMO' : devModeActive ? 'DEVELOPER' : null

  useEffect(() => {
    const updateClock = (): void => {
      setLiveTime(
        new Date().toLocaleTimeString('en-US', {
          hour: 'numeric',
          minute: '2-digit',
          second: '2-digit',
          hour12: true,
        }),
      )
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

  const apexPillShellClass = [
    'hud-corner-brackets hud-interactive-shell hud-glass relative flex h-11 min-w-[5.5rem] cursor-pointer flex-col items-center justify-center rounded-full px-5 transition-all duration-300',
    hasConnectorFailures
      ? 'border border-red-500/70 shadow-[0_0_16px_rgba(220,38,38,0.55),0_0_4px_rgba(220,38,38,0.9)] hover:border-red-400'
      : 'hover-blue-medium',
  ].join(' ')

  return (
    <div className="pointer-events-auto grid h-16 w-full min-w-0 grid-cols-3 items-center gap-2 sm:gap-3">
      {/* Left flank — hardware */}
      <div className="flex min-w-0 items-center justify-self-start gap-2 sm:gap-2.5">
        <MetricPill
          label="CPU"
          value={cpuText}
          percentage={cpuPctClamped}
          unavailable={cpuUnavailable}
          icon={Cpu}
        />
        <MetricPill
          label="RAM"
          value={ramText}
          percentage={ramPctClamped}
          unavailable={ramUnavailable}
          icon={Database}
        />
        <BriefingModeSelector
          value={briefingMode}
          onChange={onBriefingModeChange}
          profiles={profilesStatus}
          hydrated={profilesStatusHydrated}
          disabled={briefingControlsBusy}
        />
      </div>

      {/* Center — APEX identity + Sync Health popup */}
      <div
        ref={containerRef}
        className="relative z-50 justify-self-center shrink-0"
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
          className={apexPillShellClass}
          aria-expanded={isOpen}
          aria-label={
            hasConnectorFailures
              ? 'APEX sync health — connector failures detected'
              : 'APEX sync health'
          }
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <span className="hud-inner-lift flex flex-col items-center leading-none">
            <span className="font-orbitron text-sm font-bold uppercase tracking-[0.28em] text-[color:var(--hud-accent)] sm:text-base">
              APEX
            </span>
            {modeSubtitle === 'DEMO' && (
              <span
                className="mt-0.5 font-mono text-[8px] uppercase tracking-[0.22em] text-amber-400"
                data-slot="demo-mode-subtitle"
              >
                DEMO
              </span>
            )}
            {modeSubtitle === 'DEVELOPER' && (
              <span
                className="mt-0.5 font-mono text-[8px] uppercase tracking-[0.22em] text-cyan-400"
                data-slot="dev-mode-subtitle"
              >
                DEVELOPER
              </span>
            )}
          </span>
        </div>

        <div
          className={`hud-corner-brackets hud-glass hud-glass-solid absolute left-1/2 top-[calc(100%+0.5rem)] z-50 w-[min(18rem,calc(100vw-2rem))] -translate-x-1/2 origin-top rounded-2xl border border-white/10 px-4 py-3 shadow-2xl transition-all duration-300 ${
            isOpen
              ? 'pointer-events-auto translate-y-0 opacity-100'
              : 'pointer-events-none -translate-y-1 opacity-0'
          }`}
          role="dialog"
          aria-label="Sync health"
          aria-hidden={!isOpen}
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />

          <div className="flex flex-col gap-2 font-mono">
            <div className="flex items-center justify-between gap-3 text-[10px] text-zinc-500">
              <span className="flex items-center gap-1.5">
                <RotateCw className="size-3.5 animate-[spin_12s_linear_infinite]" aria-hidden />
                Sync Health
              </span>
              <span className={`${syncColorText} font-bold`}>
                {status === 'success' ? `${confidenceScore}%` : '--%'}
              </span>
            </div>
            <div className="flex items-center justify-center gap-0.5 py-1">{syncBlocks}</div>
            <p
              className={`truncate text-[9px] leading-tight ${
                hasConnectorFailures ? 'text-amber-300/90' : 'text-zinc-500'
              }`}
            >
              {healthSummary.text}
            </p>
          </div>
        </div>
      </div>

      {/* Right flank — disk / net / clock */}
      <div className="flex min-w-0 items-center justify-self-end gap-2 sm:gap-2.5">
        <MetricPill
          label="DISK"
          value={diskText}
          percentage={diskPctClamped}
          unavailable={diskUnavailable}
          icon={HardDrive}
          className="hidden md:flex"
        />
        <StatusPill
          label="NET"
          value={isNetworkConnected ? 'Online' : 'Offline'}
          ledClass={isNetworkConnected ? 'hud-led--live' : 'hud-led--error'}
          icon={Globe}
        />
        {onOpenSettings ? (
          <button
            ref={settingsButtonRef}
            type="button"
            onClick={onOpenSettings}
            className="hud-interactive-shell hud-glass flex size-11 shrink-0 items-center justify-center rounded-full text-zinc-300 transition-colors hover:text-[color:var(--hud-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label="Open settings"
          >
            <span className="hud-inner-lift inline-flex items-center justify-center">
              <Settings className="size-3.5" strokeWidth={2} aria-hidden="true" />
            </span>
          </button>
        ) : null}
        <div className="hidden sm:block">
          <ClockPill time={liveTime} />
        </div>
      </div>
    </div>
  )
}
