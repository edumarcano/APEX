import { ChevronRight, Clock, FileText, Volume2, X } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

import {
  attentionCurtainRevealed,
  attentionShellClass,
  type AttentionTier,
} from '../lib/attentionTier'
import { API_ENDPOINTS } from '../lib/api'
import type { BriefingMode } from '../types/settings'
import type { DigestPayload, SystemState } from '../types/telemetry'

const BRIEFING_HISTORY_ENDPOINT = API_ENDPOINTS.briefingHistory

const BRIEFING_MODE_OPTIONS: readonly { value: BriefingMode; label: string }[] = [
  { value: 'comet', label: 'Comet — Cloud' },
  { value: 'lynx', label: 'Lynx — Quick Local' },
  { value: 'acinonyx', label: 'Acinonyx — Balanced Local' },
  { value: 'neofelis', label: 'Neofelis — Capable Local' },
  { value: 'structured_digest', label: 'Structured Digest — No Model' },
]

export interface BriefingDigestProps {
  insights: string[]
  briefingText: string
  status: SystemState
  isLoading: boolean
  className?: string
  defaultTab?: 'insights' | 'briefing'
  /** When true, renders a single condensed summary row instead of the full insight list (e.g. while the console tray is open). */
  isCompact?: boolean
  /** Pipeline attention tier — glass power + body curtain. */
  attentionTier?: AttentionTier
  /** Curtain unlock delay in ms. */
  attentionStaggerMs?: number
  /** Overview is activated — show empty-state Generate Briefing. */
  activated?: boolean
  briefingMode: BriefingMode
  onBriefingModeChange: (mode: BriefingMode) => void
  onGenerateBriefing?: () => void
  onRefreshAllAndGenerate?: () => void
  onSpeakBriefing?: () => void
  generateDisabled?: boolean
  speakDisabled?: boolean
  showSpeakAction?: boolean
  synthesisLabel?: string | null
  fallbackReason?: string | null
}

export function BriefingDigest({
  insights,
  briefingText,
  status,
  isLoading,
  className,
  defaultTab = 'insights',
  isCompact = false,
  attentionTier = 'dormant',
  attentionStaggerMs = 0,
  activated = false,
  briefingMode,
  onBriefingModeChange,
  onGenerateBriefing,
  onRefreshAllAndGenerate,
  onSpeakBriefing,
  generateDisabled = false,
  speakDisabled = false,
  showSpeakAction = false,
  synthesisLabel = null,
  fallbackReason = null,
}: BriefingDigestProps): ReactElement {
  const labelId = 'briefing-digest-title'
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'insights' | 'briefing'>(defaultTab)
  const trimmedBriefing = briefingText.trim()
  const curtainRevealed = attentionCurtainRevealed(attentionTier)
  const curtainStyle: CSSProperties | undefined =
    attentionStaggerMs > 0
      ? ({ '--attention-stagger': `${attentionStaggerMs}ms` } as CSSProperties)
      : undefined
  const shellClass = attentionShellClass(attentionTier)

  const actionButtons =
    activated && onGenerateBriefing ? (
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="briefing-mode-select">
          Briefing Mode
        </label>
        <select
          id="briefing-mode-select"
          value={briefingMode}
          onChange={(event) => onBriefingModeChange(event.target.value as BriefingMode)}
          disabled={isLoading}
          className="rounded-md border border-white/10 bg-zinc-950/50 px-2 py-1.5 font-mono text-[10px] uppercase tracking-widest text-zinc-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
          data-slot="briefing-mode-select"
        >
          {BRIEFING_MODE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onGenerateBriefing}
          disabled={generateDisabled || isLoading}
          className="inline-flex rounded-md border border-[#0F4DB8]/40 bg-[#0F4DB8]/10 px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[#FBBF24] transition-colors hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
          data-slot="generate-briefing-trigger"
        >
          Generate Briefing
        </button>
        {onRefreshAllAndGenerate ? (
          <button
            type="button"
            onClick={onRefreshAllAndGenerate}
            disabled={generateDisabled || isLoading}
            className="inline-flex rounded-md border border-white/15 bg-white/5 px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200 transition-colors hover:border-white/25 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            data-slot="refresh-all-and-generate-trigger"
          >
            Refresh All &amp; Generate
          </button>
        ) : null}
        {showSpeakAction && onSpeakBriefing && trimmedBriefing.length > 0 ? (
          <button
            type="button"
            onClick={onSpeakBriefing}
            disabled={speakDisabled || isLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-white/15 bg-white/5 px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200 transition-colors hover:border-white/25 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            data-slot="speak-briefing-trigger"
          >
            <Volume2 className="size-3" strokeWidth={2} aria-hidden />
            Speak / Replay
          </button>
        ) : null}
      </div>
    ) : null

  const statusMeta =
    synthesisLabel || fallbackReason ? (
      <p className="text-[11px] leading-relaxed text-zinc-400" role="status">
        {[synthesisLabel, fallbackReason ? `Fallback: ${fallbackReason}` : null]
          .filter(Boolean)
          .join(' · ')}
      </p>
    ) : null

  if (isCompact) {
    const compactMessage =
      isLoading || status === 'idle'
        ? 'Compiling briefing…'
        : insights.length > 0
          ? `${insights.length} insight${insights.length === 1 ? '' : 's'} ready — open the Briefing tab`
          : 'No current highlights.'

    return (
      <section
        className={`hud-corner-brackets hud-interactive-shell relative flex shrink-0 flex-none items-center gap-3 overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] px-3 py-2 hud-glass transition-all duration-1000 ease-in-out shadow-none ${shellClass}${className ? ` ${className}` : ''}`}
        aria-labelledby={labelId}
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
        <div className="hud-inner-lift flex min-w-0 flex-1 items-center gap-3">
          <span className="hud-icon-badge size-6 shrink-0">
            <FileText className="size-3.5 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
          </span>
          <p id={labelId} className="min-w-0 flex-1 truncate text-xs font-medium text-[color:var(--hud-text)]">
            {compactMessage}
          </p>
        </div>
      </section>
    )
  }

  return (
    <section
      className={`hud-corner-brackets hud-interactive-shell relative flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] p-[var(--hud-panel-pad)] hud-glass transition-all duration-1000 ease-in-out shadow-none ${shellClass}${className ? ` ${className}` : ''}`}
      aria-labelledby={labelId}
    >
      <span className="hud-corner-bl" aria-hidden />
      <span className="hud-corner-br" aria-hidden />
      <header className="hud-inner-lift mb-3 shrink-0">
        <div className="flex min-h-9 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="hud-icon-badge size-7 shrink-0">
            <FileText className="size-4 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
          </span>
          <h2 id={labelId} className="min-w-0 truncate font-orbitron text-sm font-semibold leading-none tracking-[0.12em] text-[color:var(--hud-text)]">
            Briefing Highlights
          </h2>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex rounded-lg border border-white/10 bg-zinc-950/30 p-0.5">
            <button
              type="button"
              onClick={() => setActiveTab('insights')}
              className={[
                'rounded-md px-2 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors',
                activeTab === 'insights'
                  ? 'bg-[#0F4DB8]/20 text-[#7EB3FF]'
                  : 'text-zinc-500 hover:text-zinc-300',
              ].join(' ')}
              aria-pressed={activeTab === 'insights'}
            >
              Insights
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('briefing')}
              className={[
                'rounded-md px-2 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors',
                activeTab === 'briefing'
                  ? 'bg-[#FBBF24]/10 text-[#FBBF24]'
                  : 'text-zinc-500 hover:text-zinc-300',
              ].join(' ')}
              aria-pressed={activeTab === 'briefing'}
            >
              Briefing
            </button>
          </div>
          {status === 'success' || (activated && (insights.length > 0 || trimmedBriefing.length > 0)) ? (
            <button
              type="button"
              onClick={() => setIsModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 px-2 py-1 text-[10px] font-mono uppercase tracking-widest text-[color:var(--hud-text)] transition-colors hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            >
              <Clock className="size-3 text-[color:var(--hud-accent)]" strokeWidth={2.25} />
              <span>History</span>
            </button>
          ) : null}
        </div>
        </div>
        <div className="hud-header-divider mt-3" aria-hidden />
      </header>

      <div
        className={[
          'hud-inner-lift flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden attention-curtain',
          curtainRevealed ? 'attention-curtain--revealed' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={curtainStyle}
      >
        {activeTab === 'briefing' ? (
          trimmedBriefing.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
                {activated
                  ? 'No briefing transcript yet.'
                  : 'Initiate system synthesis to compile briefing transcript.'}
              </p>
              {actionButtons}
              {statusMeta}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-3">
              {actionButtons}
              {statusMeta}
              <div className="list-fade-mask min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin">
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-zinc-200">
                  {trimmedBriefing}
                </p>
              </div>
            </div>
          )
        ) : (
          <>
            {isLoading || (!activated && status === 'idle') ? (
              <div className="space-y-2">
                <div className="h-3 bg-white/5 rounded animate-pulse w-full" />
                <div className="h-3 bg-white/5 rounded animate-pulse w-5/6" />
                <div className="h-3 bg-white/5 rounded animate-pulse w-4/5" />
              </div>
            ) : insights.length === 0 ? (
              <div className="space-y-3">
                <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
                  No current highlights.
                </p>
                {actionButtons}
                {statusMeta}
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-3">
                {actionButtons}
                {statusMeta}
                <ul className="list-fade-mask min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 scrollbar-thin">
                  {insights.map((insight, index) => (
                    <li key={index} className="flex items-start gap-3 text-sm leading-relaxed text-[color:var(--hud-text)]">
                      <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
                      <span className="text-zinc-200">{insight}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      {isModalOpen && createPortal(<HistoryLedgerModal onClose={() => setIsModalOpen(false)} />, document.body)}
    </section>
  )
}

interface HistoryLedgerModalProps {
  onClose: () => void
}

interface BriefingHistoryItem {
  id: number
  timestamp: string
  briefing: string
  digest?: DigestPayload | null
  digest_status?: 'valid' | 'legacy' | 'malformed' | 'zero_health'
  metadata?: {
    run_id?: string | null
    [key: string]: unknown
  } | null
}


function formatHistoryTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function HistoryLedgerModal({ onClose }: HistoryLedgerModalProps): ReactElement {
  const [isLoading, setIsLoading] = useState(true)
  const [history, setHistory] = useState<BriefingHistoryItem[]>([])

  const handleBackdropClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        onClose()
      }
    },
    [onClose],
  )

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  useEffect(() => {
    let cancelled = false

    const loadHistory = async () => {
      setIsLoading(true)

      try {
        const response = await fetch(BRIEFING_HISTORY_ENDPOINT)
        if (!response.ok) {
          throw new Error(`History fetch failed (${response.status})`)
        }

        const payload = (await response.json()) as BriefingHistoryItem[]
        if (!cancelled) {
          setHistory(payload)
        }
      } catch {
        if (!cancelled) {
          setHistory([])
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadHistory()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-md transition-opacity duration-300"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        className="relative rounded-2xl border border-white/10 hud-glass max-w-2xl w-full max-h-[80vh] flex flex-col p-6 shadow-2xl transition-all duration-300 scale-100 opacity-100"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-ledger-title"
      >
        <header className="mb-4 flex shrink-0 items-center justify-between gap-4">
          <h2
            id="history-ledger-title"
            className="font-orbitron text-sm font-semibold tracking-[0.12em] text-[color:var(--hud-text)]"
          >
            Transcript History Ledger
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 p-1.5 text-[color:var(--hud-text)] transition-colors hover:bg-white/10 hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label="Close history ledger"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </header>

        <div className="overflow-y-auto space-y-4 pr-1 scrollbar-thin flex-1 min-h-0">
          {isLoading ? (
            <div className="space-y-2">
              <div className="h-3 rounded bg-white/5 animate-pulse w-full" />
              <div className="h-3 rounded bg-white/5 animate-pulse w-5/6" />
              <div className="h-3 rounded bg-white/5 animate-pulse w-4/5" />
            </div>
          ) : history.length === 0 ? (
            <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
              No transcript history available.
            </p>
          ) : (
            history.map((item) => {
              const insights = item.digest?.insights ?? []

              return (
                <div
                  key={item.id}
                  className="border border-white/5 bg-white/5 p-4 rounded-xl space-y-2"
                >
                  <div className="flex items-center gap-2 text-xs font-medium text-[color:var(--hud-accent)]">
                    <Clock className="size-3.5 shrink-0" strokeWidth={2} aria-hidden="true" />
                    <time dateTime={item.timestamp}>{formatHistoryTimestamp(item.timestamp)}</time>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
                    {item.briefing}
                  </p>
                  {insights.length > 0 ? (
                    <div className="space-y-2 pt-1">
                      <h3 className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--hud-accent)] opacity-80">
                        Summary Insights
                      </h3>
                      <ul className="space-y-2">
                        {insights.map((insight, index) => (
                          <li
                            key={`${item.id}-insight-${index}`}
                            className="flex items-start gap-2 text-sm leading-relaxed text-[color:var(--hud-text)]"
                          >
                            <ChevronRight
                              className="mt-0.5 size-3.5 shrink-0 text-[#FBBF24]"
                              strokeWidth={2.5}
                              aria-hidden="true"
                            />
                            <span className="text-zinc-200">{insight}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
