import { useState, type ReactElement } from 'react'

import type { SystemState } from '../types/telemetry'

export type ConfidenceBadgeProps = {
  confidenceScore: number
  failedConnectors: string[]
  status: SystemState
  className?: string
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

function resolveConfidenceTier(score: number): {
  badgeClass: string
  label: string
} {
  if (score >= 90) {
    return {
      badgeClass:
        'border-emerald-500/40 bg-emerald-950/30 text-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.15)]',
      label: 'High Confidence',
    }
  }
  if (score >= 50) {
    return {
      badgeClass:
        'border-amber-500/40 bg-amber-950/30 text-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.15)]',
      label: 'Moderate Confidence',
    }
  }
  return {
    badgeClass:
      'border-red-500/40 bg-red-950/30 text-red-400 shadow-[0_0_8px_rgba(220,38,38,0.15)]',
    label: 'Low Confidence',
  }
}

const PENDING_BADGE_CLASS =
  'border-white/10 bg-zinc-950/30 text-zinc-500'

export function ConfidenceBadge({
  confidenceScore,
  failedConnectors,
  status,
  className = '',
}: ConfidenceBadgeProps): ReactElement {
  const [tooltipOpen, setTooltipOpen] = useState(false)
  const isCalculated = status === 'success'
  const tier = resolveConfidenceTier(confidenceScore)
  const displayScore = isCalculated
    ? `${Math.round(confidenceScore)}%`
    : '—%'
  const badgeClass = isCalculated ? tier.badgeClass : PENDING_BADGE_CLASS
  const ariaLabel = isCalculated
    ? `Sync health ${Math.round(confidenceScore)} percent. ${tier.label}.`
    : 'Sync health pending calculation.'

  const showTooltip = (): void => {
    setTooltipOpen(true)
  }

  const hideTooltip = (): void => {
    setTooltipOpen(false)
  }

  return (
    <div
      className={`relative inline-flex ${className}`.trim()}
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
      onFocus={showTooltip}
      onBlur={hideTooltip}
    >
      <span
        tabIndex={0}
        role="status"
        aria-label={ariaLabel}
        className={`inline-flex cursor-default items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest outline-none transition-colors duration-500 ease-in-out focus-visible:ring-2 focus-visible:ring-white/20 ${badgeClass}`}
        data-slot="confidence-badge"
      >
        <span aria-hidden="true">{displayScore}</span>
        <span className="hidden sm:inline" aria-hidden="true">
          Sync Health
        </span>
      </span>

      {tooltipOpen && (
        <div
          className="absolute top-full right-0 z-50 mt-2 w-64 rounded-xl border border-white/10 bg-zinc-950/80 p-3 text-xs backdrop-blur-md hud-glass"
          role="tooltip"
          data-slot="confidence-tooltip"
        >
          <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-[color:var(--hud-muted-text)]">
            Connector Status
          </p>
          {failedConnectors.length === 0 ? (
            <p className="leading-relaxed text-emerald-400/90">
              All connectors fully functional
            </p>
          ) : (
            <ul className="space-y-1 leading-relaxed text-[color:var(--hud-text)]">
              {failedConnectors.map((connectorId) => (
                <li key={connectorId}>
                  • {formatConnectorLabel(connectorId)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
