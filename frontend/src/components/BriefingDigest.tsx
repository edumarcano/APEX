import { ChevronRight, Clock, FileText, X } from 'lucide-react'
import { useCallback, useEffect, useState, type MouseEvent, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

import type { DigestPayload, SystemState } from '../types/telemetry'

const BRIEFING_HISTORY_ENDPOINT = 'http://127.0.0.1:8000/api/v1/briefings/history'

export interface BriefingDigestProps {
  insights: string[]
  status: SystemState
  isLoading: boolean
  className?: string
  /** When true, renders a single condensed summary line instead of the full insight list (e.g. while the console tray is open). */
  isCompact?: boolean
}

export function BriefingDigest({ insights, status, isLoading, className, isCompact = false }: BriefingDigestProps): ReactElement {
  const labelId = 'briefing-digest-title'
  const [isModalOpen, setIsModalOpen] = useState(false)

  if (isCompact) {
    const compactMessage =
      isLoading || status === 'idle'
        ? 'Compiling briefing…'
        : insights.length > 0
          ? `${insights.length} insight${insights.length === 1 ? '' : 's'} ready — open the Briefing tab`
          : 'No current highlights.'

    return (
      <section
        className={`relative flex shrink-0 flex-none items-center gap-3 overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] hover-blue-subtle px-3 py-2 hud-glass transition-all duration-1000 ease-in-out shadow-none${className ? ` ${className}` : ''}`}
        aria-labelledby={labelId}
      >
        <span className="hud-icon-badge size-6 shrink-0">
          <FileText className="size-3.5 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
        </span>
        <p id={labelId} className="min-w-0 flex-1 truncate text-xs font-medium text-[color:var(--hud-text)]">
          {compactMessage}
        </p>
      </section>
    )
  }

  return (
    <section
      className={`relative flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] hover-blue-subtle p-[var(--hud-panel-pad)] hud-glass transition-all duration-1000 ease-in-out shadow-none${className ? ` ${className}` : ''}`}
      aria-labelledby={labelId}
    >
      <header className="mb-4 flex min-h-9 shrink-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <FileText className="size-5 shrink-0 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
          <h2 id={labelId} className="min-w-0 text-sm font-semibold leading-normal tracking-tight text-[color:var(--hud-text)]">
            Briefing Highlights
          </h2>
        </div>
        {status === 'success' && (
          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 px-2 py-1 text-[10px] font-mono uppercase tracking-widest text-[color:var(--hud-text)] transition-colors hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
          >
            <Clock className="size-3 text-[color:var(--hud-accent)]" strokeWidth={2.25} />
            <span>History</span>
          </button>
        )}
      </header>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {isLoading || status === 'idle' ? (
          <div className="space-y-2">
            <div className="h-3 bg-white/5 rounded animate-pulse w-full" />
            <div className="h-3 bg-white/5 rounded animate-pulse w-5/6" />
            <div className="h-3 bg-white/5 rounded animate-pulse w-4/5" />
          </div>
        ) : insights.length === 0 ? (
          <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">No current highlights.</p>
        ) : (
          <ul className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 scrollbar-thin">
            {insights.map((insight, index) => (
              <li key={index} className="flex items-start gap-3 text-sm leading-relaxed text-[color:var(--hud-text)]">
                <span className="text-[#FBBF24] font-bold font-mono select-none shrink-0">{`>`}</span>
                <span className="text-zinc-200">{insight}</span>
              </li>
            ))}
          </ul>
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
            className="text-sm font-semibold tracking-tight text-[color:var(--hud-text)]"
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
                      <h3 className="text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80">
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
