import { LineChart } from 'lucide-react'
import { useId, useMemo, type CSSProperties, type ReactElement } from 'react'

import {
  attentionCurtainRevealed,
  attentionShellClass,
  type AttentionTier,
} from '../lib/attentionTier'
import type { MarketResponse, MarketTickerItem } from '../types/telemetry'

type MarketTickerCardProps = {
  data: MarketResponse | null
  isLoading?: boolean
  enabled?: boolean
  className?: string
  /** When true, renders a single condensed row of symbol/percent chips instead of the full ticker grid. */
  isCompact?: boolean
  /** Pipeline attention tier — glass power + body curtain (shell-only in compact). */
  attentionTier?: AttentionTier
  /** Curtain unlock delay in ms for staggered reveals within a shared step. */
  attentionStaggerMs?: number
}

const POSITIVE_COLOR = '#39FF88'
const NEGATIVE_COLOR = '#ef4444'

type MarketLedState = 'live' | 'stale' | 'loading' | 'error' | 'none'

function resolveMarketLedState(
  data: MarketResponse | null,
  isLoading: boolean,
): MarketLedState {
  if (!data) {
    return isLoading ? 'loading' : 'error'
  }
  if (data.status === 'not_configured') {
    return 'none'
  }
  if (data.status === 'provider_unavailable' || data.status === 'unavailable') {
    return 'error'
  }
  if (data.status === 'stale' || data.cooldown_active) {
    return 'stale'
  }
  return 'live'
}

const MARKET_LED_CLASS: Record<MarketLedState, string> = {
  live: 'hud-led hud-led--live size-1.5',
  stale: 'hud-led hud-led--stale size-1.5',
  loading: 'hud-led hud-led--loading size-1.5',
  error: 'hud-led hud-led--error size-1.5',
  none: '',
}

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

function resolveSparklineTrend(values: number[]): 'positive' | 'negative' | 'neutral' {
  if (values.length < 2) {
    return 'neutral'
  }
  // Backend sparkline is newest-first (index 0 = latest close).
  const newest = values[0]
  const oldest = values[values.length - 1]
  if (newest >= oldest) {
    return 'positive'
  }
  if (newest < oldest) {
    return 'negative'
  }
  return 'neutral'
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
  return resolveSparklineTrend(sparkline)
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

function Sparkline({ values }: { values: number[] }): ReactElement {
  const filterId = useId()
  const points = useMemo(() => buildSparklinePoints(values), [values])
  const sparkTrend = useMemo(() => resolveSparklineTrend(values), [values])
  const stroke =
    sparkTrend === 'positive'
      ? POSITIVE_COLOR
      : sparkTrend === 'negative'
        ? NEGATIVE_COLOR
        : '#6b7280'

  if (!points) {
    return (
      <svg
        viewBox="0 0 100 30"
        className="h-5 w-full min-w-[4rem] max-w-[5rem] overflow-visible opacity-30"
        aria-hidden
      >
        <line x1="0" y1="15" x2="100" y2="15" stroke="#4b5563" strokeWidth="1" />
      </svg>
    )
  }

  return (
    <svg
      viewBox="0 0 100 30"
      className="h-5 w-full min-w-[4rem] max-w-[5rem] overflow-visible"
      aria-hidden
    >
      <defs>
        <filter id={filterId} x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow
            dx="0"
            dy="0"
            stdDeviation="1.5"
            floodColor={stroke}
            floodOpacity="0.6"
          />
        </filter>
      </defs>
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${filterId})`}
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
      <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.18em]">{title}</p>
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
      className={`flex min-h-[4.25rem] min-w-[8rem] flex-1 flex-col justify-between gap-1 rounded-lg border border-white/[0.06] bg-zinc-950/20 px-2 py-2 ${glowClass}`}
    >
      <div className={`flex items-start justify-between gap-2 ${isStale ? 'opacity-70' : ''}`}>
        <div className="min-w-0 space-y-1">
          <span className="block font-mono text-[11px] font-semibold uppercase tracking-wider text-zinc-200">
            {ticker.symbol}
          </span>
          <p
            className={`tabular-nums text-base font-semibold leading-none ${
              isUnavailable ? 'text-zinc-500' : trend !== 'neutral' ? 'mix-blend-screen' : ''
            }`}
            style={isUnavailable ? undefined : { color: trendColor }}
          >
            {isUnavailable ? '--.--' : `$${formatPrice(ticker.price)}`}
          </p>
          <p
            className={`mt-0.5 font-mono text-[10px] tabular-nums ${
              isUnavailable ? 'text-zinc-600' : trend !== 'neutral' ? 'mix-blend-screen' : ''
            }`}
            style={isUnavailable ? undefined : { color: trendColor }}
          >
            {isUnavailable ? '--%' : formatChangePercent(ticker.change_percent)}
          </p>
        </div>
        {isStale ? (
          <span className="shrink-0 font-mono text-[9px] font-semibold uppercase tracking-wider text-amber-400/80">
            {staleBadge}
          </span>
        ) : null}
      </div>

      <div className="mt-1 flex min-h-0 w-full justify-end">
        <Sparkline values={isUnavailable ? [] : ticker.sparkline} />
      </div>
    </div>
  )
}

function CompactTickerChip({ ticker }: { ticker: MarketTickerItem }): ReactElement {
  const trend = resolveTrendDirection(ticker.change, ticker.change_percent, ticker.sparkline)
  const trendColor =
    trend === 'positive' ? POSITIVE_COLOR : trend === 'negative' ? NEGATIVE_COLOR : '#9ca3af'
  const isUnavailable = ticker.status === 'unavailable'

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/[0.06] bg-zinc-950/30 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
      <span className="text-zinc-300">{ticker.symbol}</span>
      <span style={isUnavailable ? undefined : { color: trendColor }} className={isUnavailable ? 'text-zinc-500' : ''}>
        {isUnavailable ? '--%' : formatChangePercent(ticker.change_percent)}
      </span>
    </span>
  )
}

export function MarketTickerCard({
  data,
  isLoading = false,
  enabled = true,
  className,
  isCompact = false,
  attentionTier = 'dormant',
  attentionStaggerMs = 0,
}: MarketTickerCardProps): ReactElement {
  const curtainRevealed = attentionCurtainRevealed(attentionTier)
  const curtainStyle: CSSProperties | undefined =
    attentionStaggerMs > 0
      ? ({ '--attention-stagger': `${attentionStaggerMs}ms` } as CSSProperties)
      : undefined

  const sectionClassName = [
    'hud-corner-brackets hud-interactive-shell relative flex overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02] hud-glass transition-all duration-700 ease-in-out',
    isCompact
      ? 'h-auto min-h-[3.75rem] shrink-0 flex-none flex-row items-center px-4 py-3'
      : 'h-auto min-h-0 w-full flex-none flex-col p-[var(--hud-panel-pad)]',
    attentionShellClass(attentionTier),
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const ledState = resolveMarketLedState(data, isLoading)

  const content = (() => {
    if (!enabled) {
      return (
        <SetupPanel
          tone="muted"
          title="MARKET MONITOR DISABLED"
          message="Market connector disabled in Runtime Settings."
        />
      )
    }

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
      <div className="flex h-full min-h-0 flex-wrap items-stretch gap-1.5 sm:gap-2">
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

  if (isCompact) {
    return (
      <section className={sectionClassName} aria-label="Market ticker">
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
        <div className="hud-inner-lift flex min-w-0 flex-1 items-center">
          <span className="hud-icon-badge size-7 shrink-0">
            <LineChart className="size-4 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
          </span>
          <span className="ml-3 w-16 shrink-0 truncate font-orbitron text-[10px] font-semibold uppercase tracking-[0.12em] text-[color:var(--hud-text)]">
            Market
          </span>
          <div className="ml-2.5 flex min-w-0 flex-1 items-center gap-2 overflow-x-auto scrollbar-none">
            {data && data.tickers.length > 0 ? (
              data.tickers.map((ticker) => <CompactTickerChip key={ticker.symbol} ticker={ticker} />)
            ) : (
              <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">No tickers</span>
            )}
          </div>
          {ledState !== 'none' ? (
            <span
              className={`ml-2 shrink-0 ${MARKET_LED_CLASS[ledState]}`}
              role="status"
              aria-label={`Market feed ${ledState}`}
              title={`Market feed ${ledState}`}
            />
          ) : null}
        </div>
      </section>
    )
  }

  return (
    <section className={sectionClassName} aria-label="Market ticker">
      <span className="hud-corner-bl" aria-hidden />
      <span className="hud-corner-br" aria-hidden />
      <header className="hud-inner-lift mb-2 shrink-0">
        <div className="flex min-h-9 items-center gap-2.5">
          <span className="hud-icon-badge size-7 shrink-0">
            <LineChart
              className="size-4 text-[color:var(--hud-accent)]"
              strokeWidth={1.75}
              aria-hidden
            />
          </span>
          <h2 className="min-w-0 flex-1 truncate font-orbitron text-sm font-semibold tracking-[0.12em] text-[color:var(--hud-text)]">
            Market
          </h2>
          {data && data.status !== 'not_configured' && data.status !== 'provider_unavailable' ? (
            <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.18em] text-zinc-500">
              {data.status}
            </span>
          ) : null}
          {ledState !== 'none' ? (
            <span
              className={MARKET_LED_CLASS[ledState]}
              role="status"
              aria-label={`Market feed ${ledState}`}
              title={`Market feed ${ledState}`}
            />
          ) : null}
        </div>
        <div className="hud-header-divider mt-2" aria-hidden />
      </header>
      <div
        className={[
          'hud-inner-lift min-h-0 w-full flex-1 attention-curtain',
          curtainRevealed ? 'attention-curtain--revealed' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={curtainStyle}
      >
        {content}
      </div>
    </section>
  )
}
