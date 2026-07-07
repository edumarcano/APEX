import { LineChart } from 'lucide-react'
import { useMemo, type ReactElement } from 'react'

import type { MarketResponse, MarketTickerItem } from '../types/telemetry'

type MarketTickerCardProps = {
  data: MarketResponse | null
  isLoading?: boolean
  className?: string
}

const POSITIVE_COLOR = '#39FF88'
const NEGATIVE_COLOR = '#ef4444'

function formatPrice(price: number | null): string {
  if (price === null) {
    return '--.--'
  }
  return price.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatChangePercent(changePercent: number | null): string {
  if (changePercent === null) {
    return '--%'
  }
  const sign = changePercent > 0 ? '+' : ''
  return `${sign}${changePercent.toFixed(2)}%`
}

function resolveTrendDirection(
  change: number | null,
  changePercent: number | null,
  sparkline: number[],
): 'positive' | 'negative' | 'neutral' {
  if (change !== null && change !== 0) {
    return change > 0 ? 'positive' : 'negative'
  }
  if (changePercent !== null && changePercent !== 0) {
    return changePercent > 0 ? 'positive' : 'negative'
  }
  if (sparkline.length >= 2) {
    const newest = sparkline[0]
    const oldest = sparkline[sparkline.length - 1]
    if (newest > oldest) return 'positive'
    if (newest < oldest) return 'negative'
  }
  return 'neutral'
}

function buildSparklinePoints(values: number[]): string {
  if (values.length === 0) {
    return ''
  }

  const width = 100
  const height = 30
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  return values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width
      const y = height - ((value - min) / range) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

function Sparkline({
  values,
  trend,
}: {
  values: number[]
  trend: 'positive' | 'negative' | 'neutral'
}): ReactElement {
  const points = useMemo(() => buildSparklinePoints(values), [values])
  const stroke =
    trend === 'positive' ? POSITIVE_COLOR : trend === 'negative' ? NEGATIVE_COLOR : '#6b7280'

  if (!points) {
    return (
      <svg
        viewBox="0 0 100 30"
        className="h-7 w-full min-w-[4.5rem] max-w-[5.5rem] opacity-30"
        aria-hidden
      >
        <line x1="0" y1="15" x2="100" y2="15" stroke="#4b5563" strokeWidth="1" />
      </svg>
    )
  }

  return (
    <svg
      viewBox="0 0 100 30"
      className="h-7 w-full min-w-[4.5rem] max-w-[5.5rem]"
      aria-hidden
    >
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SetupPanel({
  title,
  message,
  tone,
}: {
  title: string
  message: string
  tone: 'muted' | 'error'
}): ReactElement {
  const toneClasses =
    tone === 'error'
      ? 'border-red-500/20 bg-red-950/10 text-red-300/90'
      : 'border-amber-500/20 bg-amber-950/10 text-amber-200/90'

  return (
    <div
      className={`flex min-h-[4.5rem] flex-col justify-center rounded-xl border px-3 py-2.5 ${toneClasses}`}
    >
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.2em]">{title}</p>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-300/90">{message}</p>
    </div>
  )
}

function TickerRow({
  ticker,
  globalStatus,
  cooldownActive,
  forceUnavailable,
}: {
  ticker: MarketTickerItem
  globalStatus: MarketResponse['status']
  cooldownActive: boolean
  forceUnavailable: boolean
}): ReactElement {
  const isUnavailable =
    forceUnavailable || globalStatus === 'unavailable' || ticker.status === 'unavailable'
  const isStale =
    !isUnavailable &&
    (globalStatus === 'stale' || ticker.status === 'stale' || cooldownActive)

  const trend = resolveTrendDirection(ticker.change, ticker.change_percent, ticker.sparkline)
  const trendColor =
    trend === 'positive' ? POSITIVE_COLOR : trend === 'negative' ? NEGATIVE_COLOR : '#9ca3af'

  const glowClass =
    !isUnavailable && !isStale && trend === 'positive'
      ? 'shadow-[0_0_14px_rgba(57,255,136,0.28)] animate-[pulse_3s_ease-in-out_infinite]'
      : !isUnavailable && !isStale && trend === 'negative'
        ? 'shadow-[0_0_14px_rgba(239,68,68,0.28)] animate-[pulse_3s_ease-in-out_infinite]'
        : ''

  const staleBadge = cooldownActive ? '[COOLDOWN]' : '[STALE]'

  return (
    <div
      className={`flex min-w-[8.5rem] flex-1 flex-col gap-1.5 rounded-xl border border-white/[0.06] bg-white/[0.02] px-2.5 py-2 ${glowClass}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-zinc-200">
          {ticker.symbol}
        </span>
        {isStale ? (
          <span className="font-mono text-[9px] font-semibold uppercase tracking-wider text-amber-400/80">
            {staleBadge}
          </span>
        ) : null}
      </div>

      <div className={`flex items-end justify-between gap-2 ${isStale ? 'opacity-70' : ''}`}>
        <div className="min-w-0">
          <p
            className={`tabular-nums text-base font-semibold leading-none ${
              isUnavailable ? 'text-zinc-500' : ''
            }`}
            style={isUnavailable ? undefined : { color: trendColor }}
          >
            {isUnavailable ? '--.--' : `$${formatPrice(ticker.price)}`}
          </p>
          <p
            className={`mt-1 font-mono text-[10px] tabular-nums ${
              isUnavailable ? 'text-zinc-600' : ''
            }`}
            style={isUnavailable ? undefined : { color: trendColor }}
          >
            {isUnavailable ? '--%' : formatChangePercent(ticker.change_percent)}
          </p>
        </div>
        <Sparkline values={isUnavailable ? [] : ticker.sparkline} trend={trend} />
      </div>
    </div>
  )
}

export function MarketTickerCard({
  data,
  isLoading = false,
  className,
}: MarketTickerCardProps): ReactElement {
  const sectionClassName = [
    'relative flex h-auto min-h-0 w-full flex-none flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02] hud-glass p-[var(--hud-panel-pad)] transition-all duration-700 ease-in-out hover-blue-subtle',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const content = (() => {
    if (!data) {
      if (isLoading) {
        return (
          <SetupPanel
            tone="muted"
            title="Market Monitor"
            message="Initializing market telemetry feed…"
          />
        )
      }
      return (
        <SetupPanel
          tone="muted"
          title="Market Unavailable"
          message="Market telemetry could not be reached. Retrying on the next poll cycle."
        />
      )
    }

    if (data.status === 'not_configured') {
      return (
        <SetupPanel
          tone="muted"
          title="MARKET MONITOR OFFLINE"
          message="Define MARKET_SYMBOLS in `.env` to initialize market telemetry."
        />
      )
    }

    if (data.status === 'provider_unavailable') {
      return (
        <SetupPanel
          tone="error"
          title="PROVIDER ERROR"
          message="Verify `ALPHA_VANTAGE_API_KEY` is configured and active."
        />
      )
    }

    const forceUnavailable = data.status === 'unavailable'

    if (data.tickers.length === 0) {
      return (
        <SetupPanel
          tone="muted"
          title="Market Unavailable"
          message="No ticker symbols are available for display."
        />
      )
    }

    return (
      <div className="flex flex-wrap gap-2 sm:gap-3">
        {data.tickers.map((ticker) => (
          <TickerRow
            key={ticker.symbol}
            ticker={ticker}
            globalStatus={data.status}
            cooldownActive={data.cooldown_active}
            forceUnavailable={forceUnavailable}
          />
        ))}
      </div>
    )
  })()

  return (
    <section className={sectionClassName} aria-label="Market ticker">
      <header className="mb-3 flex shrink-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <LineChart
            className="size-4 shrink-0 text-[color:var(--hud-accent)]"
            strokeWidth={1.75}
            aria-hidden
          />
          <h2 className="truncate text-sm font-semibold tracking-tight text-[color:var(--hud-text)]">
            Market
          </h2>
        </div>
        {data && data.status !== 'not_configured' && data.status !== 'provider_unavailable' ? (
          <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.18em] text-zinc-500">
            {data.status}
          </span>
        ) : null}
      </header>
      <div className="min-h-0 w-full">{content}</div>
    </section>
  )
}
