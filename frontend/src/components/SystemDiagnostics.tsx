import { useEffect, useRef, useState } from 'react'
import type { ReactElement, ReactNode, RefObject } from 'react'
import {
  Bell,
  CalendarDays,
  Clock,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Mail,
  Newspaper,
  PlugZap,
  RefreshCw,
  Settings,
  Trophy,
  type LucideIcon,
} from 'lucide-react'

import {
  type ConnectorHealthEntry,
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
  sports: 'Sports',
  f1: 'Formula 1',
  football: 'Football',
  sports_f1: 'Formula 1',
  sports_football: 'Football',
  reminders: 'Reminders',
}

const CONNECTOR_ICONS: Record<string, LucideIcon> = {
  weather: Globe,
  news: Newspaper,
  email: Mail,
  calendar: CalendarDays,
  f1: Trophy,
  football: Trophy,
  reminders: Bell,
}

function formatConnectorLabel(connectorId: string): string {
  const normalized = connectorId.trim().toLowerCase()
  return CONNECTOR_LABELS[normalized] ?? connectorId
}

type ConnectorDisplayState = 'Ready' | 'Checking' | 'Not configured' | 'Unauthorized' | 'Error' | 'Stale'

interface ConnectorDisplayRow {
  entry: ConnectorHealthEntry
  state: ConnectorDisplayState
  errorCategory: string | null
}

function getSafeErrorCategory(reasonCode: string | undefined): string | null {
  switch (reasonCode?.trim().toLowerCase()) {
    case 'missing_credentials':
    case 'configuration_failure':
      return 'Configuration required'
    case 'unauthorized':
    case 'authentication_error':
    case 'invalid_credentials':
    case 'forbidden':
      return 'Authorization required'
    case 'timeout':
    case 'network_error':
    case 'connection_error':
      return 'Connection unavailable'
    case 'throttled':
      return 'Rate limited'
    case 'provider_error':
      return 'Provider error'
    case 'partial_failure':
    case 'partial_payload':
    case 'invalid_payload':
      return 'Partial data'
    case 'database_error':
      return 'Local data error'
    default:
      return reasonCode && reasonCode !== 'ok' && reasonCode !== 'disabled'
        ? 'Connector unavailable'
        : null
  }
}

function getConnectorDisplayState(
  entry: ConnectorHealthEntry,
  checking: boolean,
): ConnectorDisplayState {
  if (checking) return 'Checking'
  if (entry.status === 'disabled' || entry.reason_code === 'missing_credentials' || entry.reason_code === 'configuration_failure') {
    return 'Not configured'
  }
  if (['unauthorized', 'authentication_error', 'invalid_credentials', 'forbidden'].includes(entry.reason_code ?? '')) {
    return 'Unauthorized'
  }
  if (entry.freshness === 'stale' || entry.reason_code === 'stale_cache') return 'Stale'
  if (entry.status === 'healthy') return 'Ready'
  return 'Error'
}

function formatCheckedAt(observedAt: string | null | undefined): string {
  if (!observedAt) return 'Last check unavailable'
  const checkedAt = Date.parse(observedAt)
  if (!Number.isFinite(checkedAt)) return 'Last check unavailable'
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - checkedAt) / 1000))
  if (elapsedSeconds < 60) return 'Checked just now'
  const elapsedMinutes = Math.floor(elapsedSeconds / 60)
  if (elapsedMinutes < 60) return `Checked ${elapsedMinutes}m ago`
  const elapsedHours = Math.floor(elapsedMinutes / 60)
  if (elapsedHours < 24) return `Checked ${elapsedHours}h ago`
  return `Checked ${Math.floor(elapsedHours / 24)}d ago`
}

function getConnectorSummary(rows: ConnectorDisplayRow[]): {
  text: string
  ledClass: string
  hasIssues: boolean
} {
  if (rows.some((row) => row.state === 'Checking')) {
    return { text: 'Connectors · Checking…', ledClass: 'bg-zinc-400', hasIssues: false }
  }
  const configured = rows.filter((row) => row.state !== 'Not configured')
  if (configured.length === 0) {
    return { text: 'Connectors · Not configured', ledClass: 'bg-zinc-500', hasIssues: false }
  }
  const ready = configured.filter((row) => row.state === 'Ready').length
  const issues = configured.length - ready
  if (issues === 0) {
    return { text: `Connectors · ${ready} ready`, ledClass: 'bg-emerald-400', hasIssues: false }
  }
  return {
    text: `Connectors · ${ready} ready · ${issues} ${issues === 1 ? 'issue' : 'issues'}`,
    ledClass: 'bg-amber-400',
    hasIssues: true,
  }
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

interface SystemDiagnosticsProps {
  diagnostics: SystemDiagnosticsPayload
  diagnosticsStatus: 'idle' | 'loading' | 'ready' | 'error'
  failedConnectors?: string[]
  connectorHealth?: ConnectorHealthEntry[]
  isCheckingConnectors?: boolean
  refreshingConnectors?: ReadonlySet<string>
  onRefreshConnectors?: () => void
  demoModeActive?: boolean
  devModeActive?: boolean
  onOpenSettings?: () => void
  settingsButtonRef?: RefObject<HTMLButtonElement | null>
  workspaceNavigation?: ReactNode
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
  failedConnectors = [],
  connectorHealth = [],
  isCheckingConnectors = false,
  refreshingConnectors = new Set<string>(),
  onRefreshConnectors,
  demoModeActive = false,
  devModeActive = false,
  onOpenSettings,
  settingsButtonRef,
  workspaceNavigation,
}: SystemDiagnosticsProps): ReactElement {
  const [isBrowserOnline, setIsBrowserOnline] = useState(navigator.onLine)
  const [isConnectorInspectorOpen, setIsConnectorInspectorOpen] = useState(false)
  const [isConnectorInspectorPinned, setIsConnectorInspectorPinned] = useState(false)
  const [liveTime, setLiveTime] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  const connectorEntries = connectorHealth.length > 0
    ? connectorHealth
    : failedConnectors.map((name) => ({
      name,
      status: 'unavailable' as const,
      freshness: 'none' as const,
      reason_code: 'provider_error',
      observed_at: null,
    }))
  const connectorRows = connectorEntries.map((entry) => ({
    entry,
    state: getConnectorDisplayState(
      entry,
      isCheckingConnectors || refreshingConnectors.has(entry.name),
    ),
    errorCategory: getSafeErrorCategory(entry.reason_code),
  }))
  const connectorSummary = getConnectorSummary(connectorRows)
  const isAnyConnectorChecking = isCheckingConnectors || refreshingConnectors.size > 0
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
    if (!isConnectorInspectorPinned) return

    const handleOutsideClick = (event: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsConnectorInspectorPinned(false)
        setIsConnectorInspectorOpen(false)
      }
    }

    window.addEventListener('mousedown', handleOutsideClick)
    return () => {
      window.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [isConnectorInspectorPinned])

  const handleConnectorInspectorToggle = (): void => {
    setIsConnectorInspectorPinned((prev) => {
      const next = !prev
      setIsConnectorInspectorOpen(next)
      return next
    })
  }

  const isInitializing = diagnosticsStatus === 'idle' || diagnosticsStatus === 'loading'
  const isNetworkConnected = isBrowserOnline && diagnosticsStatus !== 'error'

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
    <div className="pointer-events-auto grid h-full w-full min-w-0 grid-cols-3 items-center gap-2 sm:gap-3">
      {/* Left flank — system and connector health */}
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
        <div
          ref={containerRef}
          className="relative z-50"
          onMouseEnter={() => setIsConnectorInspectorOpen(true)}
          onMouseLeave={() => {
            if (!isConnectorInspectorPinned) setIsConnectorInspectorOpen(false)
          }}
        >
          <button
            type="button"
            onClick={handleConnectorInspectorToggle}
            onFocus={() => setIsConnectorInspectorOpen(true)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setIsConnectorInspectorPinned(false)
                setIsConnectorInspectorOpen(false)
                event.currentTarget.blur()
              }
            }}
            aria-expanded={isConnectorInspectorOpen}
            aria-controls="connector-health-inspector"
            className="hud-interactive-shell hud-glass flex h-11 min-w-0 items-center gap-2 rounded-full px-3 font-mono text-xs text-zinc-300 transition-colors hover:border-white/20 hover:bg-white/[0.07] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label={`${connectorSummary.text}. View connector health.`}
          >
            <PlugZap className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
            <span className={`size-1.5 shrink-0 rounded-full ${connectorSummary.ledClass}`} aria-hidden />
            <span className="whitespace-nowrap text-[10px] tracking-[0.04em] text-zinc-300">{connectorSummary.text}</span>
          </button>

          <div
            id="connector-health-inspector"
            role="dialog"
            aria-label="Connector health"
            aria-hidden={!isConnectorInspectorOpen}
            className={`hud-corner-brackets hud-glass hud-glass-solid absolute left-0 top-[calc(100%+0.5rem)] z-50 w-[min(23rem,calc(100vw-2rem))] origin-top rounded-2xl border border-white/10 p-3 shadow-2xl transition-all duration-200 ${isConnectorInspectorOpen ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0'}`}
          >
            <span className="hud-corner-bl" aria-hidden />
            <span className="hud-corner-br" aria-hidden />
            <div className="mb-2 flex items-center justify-between gap-3 border-b border-white/10 pb-2">
              <span className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-200">Connector health</span>
              <span className="font-mono text-[9px] text-zinc-500">{connectorSummary.text.replace('Connectors · ', '')}</span>
            </div>
            <ul className="space-y-1.5" aria-label="Connector status list">
              {connectorRows.map(({ entry, state, errorCategory }) => {
                const Icon = CONNECTOR_ICONS[entry.name] ?? PlugZap
                const stateTone = state === 'Ready' ? 'text-emerald-300' : state === 'Stale' ? 'text-amber-300' : state === 'Checking' ? 'text-zinc-300' : state === 'Not configured' ? 'text-zinc-500' : 'text-rose-300'
                return (
                  <li key={entry.name} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 rounded-lg bg-black/20 px-2.5 py-2 font-mono text-[10px]">
                    <span className="flex min-w-0 items-center gap-2 text-zinc-200"><Icon className="size-3.5 shrink-0 text-zinc-500" aria-hidden />{formatConnectorLabel(entry.name)}</span>
                    <span className={`text-right ${stateTone}`}>{state}</span>
                    <span className="col-start-1 mt-1 text-[9px] text-zinc-500">{formatCheckedAt(entry.observed_at)}</span>
                    {errorCategory ? <span className="col-start-2 mt-1 text-right text-[9px] text-zinc-500">{errorCategory}</span> : null}
                  </li>
                )
              })}
              {connectorRows.length === 0 ? <li className="rounded-lg bg-black/20 px-2.5 py-2 font-mono text-[10px] text-zinc-500">No connectors are configured.</li> : null}
            </ul>
            {onRefreshConnectors ? (
              <button
                type="button"
                onClick={onRefreshConnectors}
                disabled={isAnyConnectorChecking}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 font-orbitron text-[9px] uppercase tracking-[0.12em] text-zinc-200 transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <RefreshCw className={`size-3 ${isAnyConnectorChecking ? 'animate-spin' : ''}`} aria-hidden />
                {isAnyConnectorChecking ? 'Checking…' : 'Refresh checks'}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {/* Center — stable APEX identity */}
      <div className="relative z-40 justify-self-center shrink-0">
        <div className="hud-corner-brackets hud-interactive-shell hud-glass relative flex min-w-[7rem] flex-col items-center rounded-2xl px-1 py-1 transition-all duration-300 hover-blue-medium" aria-label="APEX identity">
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <div
            className="hud-inner-lift flex h-9 w-full flex-col items-center justify-center rounded-xl px-3 leading-none"
          >
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
          </div>
          {workspaceNavigation ? (
            <div className="hud-inner-lift mt-1 w-full border-t border-white/10 pt-1">
              {workspaceNavigation}
            </div>
          ) : null}
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
