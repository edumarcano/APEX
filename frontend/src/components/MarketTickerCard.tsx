import { LineChart } from 'lucide-react'
import { createPortal } from 'react-dom'
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactElement } from 'react'

import { attentionCurtainRevealed, attentionShellClass, type AttentionTier } from '../lib/attentionTier'
import type { MarketResponse, MarketTickerItem } from '../types/telemetry'

type MarketTickerCardProps = {
  data: MarketResponse | null
  isLoading?: boolean
  enabled?: boolean
  className?: string
  isCompact?: boolean
  attentionTier?: AttentionTier
  attentionStaggerMs?: number
}

const POSITIVE = '#39FF88'
const NEGATIVE = '#ef4444'

function formatPrice(value: number | null): string {
  if (value === null) return '--.--'
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPercent(value: number | null): string {
  if (value === null) return '--%'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function trend(ticker: MarketTickerItem): 'positive' | 'negative' | 'neutral' {
  if (ticker.period_return_percent === null || ticker.period_return_percent === 0) return 'neutral'
  return ticker.period_return_percent > 0 ? 'positive' : 'negative'
}

function color(ticker: MarketTickerItem): string {
  return trend(ticker) === 'positive' ? POSITIVE : trend(ticker) === 'negative' ? NEGATIVE : '#9ca3af'
}

function points(ticker: MarketTickerItem): string {
  const values = ticker.history.map((bar) => bar.close)
  if (values.length < 2) return ''
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const range = maximum - minimum || 1
  return values.map((value, index) => `${(index / (values.length - 1) * 100).toFixed(2)},${(30 - (value - minimum) / range * 30).toFixed(2)}`).join(' ')
}

function Sparkline({ ticker }: { ticker: MarketTickerItem }): ReactElement {
  const filterId = useId()
  const line = useMemo(() => points(ticker), [ticker])
  const stroke = color(ticker)
  return <svg viewBox="0 0 100 30" className="h-5 w-full min-w-0" aria-hidden>
    <defs><filter id={filterId} x="-20%" y="-20%" width="140%" height="140%"><feDropShadow stdDeviation="1.25" floodColor={stroke} floodOpacity="0.55" /></filter></defs>
    {line ? <polyline points={line} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" filter={`url(#${filterId})`} /> : <line x1="0" y1="15" x2="100" y2="15" stroke="#4b5563" strokeWidth="1" />}
  </svg>
}

function DetailPopover({ ticker, anchor, onClose }: { ticker: MarketTickerItem; anchor: DOMRect; onClose: () => void }): ReactElement {
  const style: CSSProperties = { left: Math.max(8, Math.min(anchor.left, window.innerWidth - 230)), top: Math.min(anchor.bottom + 8, window.innerHeight - 170), width: 222 }
  useEffect(() => {
    const dismiss = (event: KeyboardEvent): void => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', dismiss)
    return () => window.removeEventListener('keydown', dismiss)
  }, [onClose])
  return <div role="tooltip" style={style} className="hud-glass hud-glass-solid fixed z-[100] rounded-xl border border-white/10 px-3 py-2.5 shadow-2xl">
    <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">{ticker.symbol} · daily close</p>
    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-[10px]">
      <dt className="text-zinc-500">Period return</dt><dd style={{ color: color(ticker) }} className="text-right">{formatPercent(ticker.period_return_percent)}</dd>
      <dt className="text-zinc-500">Range</dt><dd className="text-right text-zinc-200">{ticker.period_low === null || ticker.period_high === null ? '—' : `$${formatPrice(ticker.period_low)}–${formatPrice(ticker.period_high)}`}</dd>
      <dt className="text-zinc-500">Volume</dt><dd className="text-right text-zinc-200">{ticker.volume_ratio === null ? '—' : `${ticker.volume_ratio.toFixed(2)}× avg`}</dd>
      <dt className="text-zinc-500">Close date</dt><dd className="text-right text-zinc-200">{ticker.close_date ?? '—'}</dd>
      <dt className="text-zinc-500">Freshness</dt><dd className="text-right text-zinc-200">{ticker.freshness.replace('_', ' ')}</dd>
    </dl>
  </div>
}

function TickerCell({ ticker, onOpen }: { ticker: MarketTickerItem; onOpen: (ticker: MarketTickerItem, target: HTMLElement) => void }): ReactElement {
  const unavailable = ticker.status === 'unavailable'
  return <button type="button" onClick={(event) => onOpen(ticker, event.currentTarget)} onFocus={(event) => onOpen(ticker, event.currentTarget)} onMouseEnter={(event) => onOpen(ticker, event.currentTarget)} className="min-w-0 rounded-lg border border-white/[0.06] bg-zinc-950/20 px-2 py-1.5 text-left transition-colors hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8]">
    <span className="flex items-center justify-between gap-1"><span className="truncate font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-200">{ticker.symbol}</span><span className={`font-mono text-[9px] ${ticker.freshness === 'stale' ? 'text-amber-400/80' : 'text-zinc-500'}`}>{ticker.freshness === 'stale' ? 'STALE' : ''}</span></span>
    <span className={`mt-1 block truncate tabular-nums text-sm font-semibold ${unavailable ? 'text-zinc-500' : ''}`} style={unavailable ? undefined : { color: color(ticker) }}>{unavailable ? '--.--' : `$${formatPrice(ticker.price)}`}</span>
    <span className={`block font-mono text-[9px] tabular-nums ${unavailable ? 'text-zinc-600' : ''}`} style={unavailable ? undefined : { color: ticker.change_percent === null || ticker.change_percent === 0 ? '#9ca3af' : ticker.change_percent > 0 ? POSITIVE : NEGATIVE }}>{unavailable ? '--%' : formatPercent(ticker.change_percent)}</span>
    <span className="mt-1 block"><Sparkline ticker={ticker} /></span>
  </button>
}

export function MarketTickerCard({ data, isLoading = false, enabled = true, className, isCompact = false, attentionTier = 'dormant', attentionStaggerMs = 0 }: MarketTickerCardProps): ReactElement {
  const [detail, setDetail] = useState<{ ticker: MarketTickerItem; anchor: DOMRect } | null>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const curtainRevealed = attentionCurtainRevealed(attentionTier)
  const curtainStyle = attentionStaggerMs > 0 ? ({ '--attention-stagger': `${attentionStaggerMs}ms` } as CSSProperties) : undefined
  useEffect(() => {
    const closeOutside = (event: MouseEvent): void => { if (sectionRef.current && !sectionRef.current.contains(event.target as Node)) setDetail(null) }
    document.addEventListener('mousedown', closeOutside)
    return () => document.removeEventListener('mousedown', closeOutside)
  }, [])
  const openDetail = (ticker: MarketTickerItem, target: HTMLElement): void => setDetail({ ticker, anchor: target.getBoundingClientRect() })
  const shell = ['hud-corner-brackets hud-interactive-shell relative flex overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02] hud-glass transition-all duration-700 ease-in-out', isCompact ? 'h-auto min-h-[3.75rem] shrink-0 flex-row items-center px-4 py-3' : 'h-auto min-h-0 w-full flex-none flex-col p-[var(--hud-panel-pad)]', attentionShellClass(attentionTier), className].filter(Boolean).join(' ')
  const content = !enabled ? <p className="text-[11px] text-amber-200/90">Market connector disabled in Runtime Settings.</p> : !data ? <p className="text-[11px] text-zinc-400">{isLoading ? 'Initializing market telemetry feed…' : 'Market telemetry is unavailable. Refresh telemetry to retry.'}</p> : data.status === 'unavailable' && data.reason_code === 'not_configured' ? <p className="text-[11px] text-amber-200/90">Add ticker symbols in Runtime Settings and define `ALPHA_VANTAGE_API_KEY` in `.env`.</p> : data.tickers.length === 0 ? <p className="text-[11px] text-zinc-400">No ticker symbols are available for display.</p> : <div className={`grid min-h-0 w-full gap-1.5 sm:gap-2 ${data.tickers.length === 1 ? 'grid-cols-1' : data.tickers.length === 2 ? 'grid-cols-2' : data.tickers.length === 3 ? 'grid-cols-3' : 'grid-cols-2 sm:grid-cols-4'}`}>{data.tickers.map((ticker) => <TickerCell key={ticker.symbol} ticker={ticker} onOpen={openDetail} />)}</div>
  if (isCompact) return <section ref={sectionRef} className={shell} aria-label="Market ticker"><span className="hud-corner-bl" aria-hidden /><span className="hud-corner-br" aria-hidden /><LineChart className="size-4 shrink-0 text-[color:var(--hud-accent)]" aria-hidden /><span className="ml-3 mr-2 font-orbitron text-[10px] uppercase tracking-[0.12em]">Market</span><div className="flex min-w-0 gap-2 overflow-x-auto">{data?.tickers.map((ticker) => <span key={ticker.symbol} className="font-mono text-[10px] text-zinc-300">{ticker.symbol} {formatPercent(ticker.change_percent)}</span>)}</div></section>
  return <section ref={sectionRef} className={shell} aria-label="Market ticker"><span className="hud-corner-bl" aria-hidden /><span className="hud-corner-br" aria-hidden /><header className="hud-inner-lift mb-2 shrink-0"><div className="flex min-h-9 items-center gap-2.5"><span className="hud-icon-badge size-7 shrink-0"><LineChart className="size-4 text-[color:var(--hud-accent)]" aria-hidden /></span><h2 className="flex-1 font-orbitron text-sm font-semibold tracking-[0.12em] text-[color:var(--hud-text)]">Market</h2><span className="font-mono text-[9px] uppercase tracking-[0.18em] text-zinc-500">Daily · 20 sessions</span></div><div className="hud-header-divider mt-2" aria-hidden /></header><div className={`hud-inner-lift min-h-0 w-full flex-1 attention-curtain ${curtainRevealed ? 'attention-curtain--revealed' : ''}`} style={curtainStyle}>{content}</div>{detail && typeof document !== 'undefined' ? createPortal(<DetailPopover ticker={detail.ticker} anchor={detail.anchor} onClose={() => setDetail(null)} />, document.body) : null}</section>
}
