import { ChevronRight, Clock, X } from 'lucide-react'
import { useCallback, useEffect, useId, useState, type ReactElement, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'

import type { DigestPayload, SystemState } from '../types/telemetry'

const BRIEFING_HISTORY_ENDPOINT = 'http://127.0.0.1:8000/api/v1/briefings/history'

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

export type BriefingPanelProps = {
  briefing: string
  status: SystemState
  error: string | null
  isLoading: boolean
  isSpeaking: boolean
}

function SpeakingBorderMask(): ReactElement {
  return (
    <>
      <div
        className="absolute -inset-[200%] animate-border-spin bg-[conic-gradient(from_0deg,transparent_45%,#FBBF24_50%,transparent_55%)] opacity-90 blur-[1px]"
        aria-hidden="true"
      />
      <div
        className="absolute inset-[1.5px] rounded-[15px] bg-[color:var(--hud-panel-bg)] z-10"
        aria-hidden="true"
      />
    </>
  )
}

function sectionShellClassName(isSpeakingActive: boolean, extra = ''): string {
  const borderClass = isSpeakingActive
    ? 'border-amber-500/80 shadow-[0_0_12px_rgba(251,191,36,0.15)]'
    : 'border-[color:var(--hud-border-color)]'

  return [
    `rounded-2xl border ${borderClass} p-[var(--hud-panel-pad)] hud-glass hover-warm-subtle`,
    'transition-all duration-1000 ease-in-out shadow-none',
    extra,
  ]
    .filter(Boolean)
    .join(' ')
}

function BriefingStream({
  briefing,
  status,
  error,
  isLoading,
  isSpeaking,
}: BriefingPanelProps): ReactElement {
  const labelId = useId()
  const rawText = briefing.trim()
  const [revealed, setRevealed] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)

  useEffect(() => {
    if (status !== 'success' || rawText.length === 0) {
      setRevealed(false)
      return undefined
    }

    setRevealed(false)
    const frameId = window.requestAnimationFrame(() => {
      setRevealed(true)
    })

    return () => {
      window.cancelAnimationFrame(frameId)
    }
  }, [status, rawText])

  if (isLoading || status === 'idle') {
    return (
      <section
        className={sectionShellClassName(
          isSpeaking,
          'relative overflow-hidden group flex h-full min-h-56 flex-col justify-center md:min-h-72',
        )}
        aria-labelledby={labelId}
        aria-busy="true"
      >
        {isSpeaking ? <SpeakingBorderMask /> : null}
        <div className="relative z-20">
          <h2
            id={labelId}
            className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
          >
            Core Briefing
          </h2>
          <p className="text-sm leading-relaxed text-[color:var(--hud-text)] opacity-80">
            Fetching briefing stream…
          </p>
        </div>
      </section>
    )
  }

  if (status === 'error') {
    return (
      <section
        className={sectionShellClassName(
          isSpeaking,
          'relative overflow-hidden group flex h-full min-h-56 flex-col justify-center md:min-h-72',
        )}
        aria-labelledby={labelId}
      >
        <div className="relative z-20">
          <h2
            id={labelId}
            className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
          >
            Core Briefing
          </h2>
          <p className="text-sm leading-relaxed text-[color:var(--hud-text)]">
            {error ?? 'Briefing unavailable.'}
          </p>
        </div>
      </section>
    )
  }

  if (rawText.length === 0) {
    return (
      <section
        className={sectionShellClassName(isSpeaking, 'relative overflow-hidden group')}
        aria-labelledby={labelId}
      >
        {isSpeaking ? <SpeakingBorderMask /> : null}
        <div className="relative z-20">
          <h2
            id={labelId}
            className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
          >
            Core Briefing
          </h2>
          <p className="text-sm leading-relaxed text-[color:var(--hud-text)]">
            No briefing content.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section
      className={sectionShellClassName(isSpeaking, 'relative overflow-hidden group')}
      aria-labelledby={labelId}
    >
      {isSpeaking ? <SpeakingBorderMask /> : null}
      <div className="relative z-20">
        <h2
          id={labelId}
          className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
        >
          Core Briefing
        </h2>
        <div
          className={`briefing-curtain min-h-[4.5rem]${revealed ? ' briefing-curtain--revealed' : ''}`}
          aria-live="polite"
          aria-atomic="true"
        >
          <span className="block whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]">
            {rawText}
          </span>
        </div>
        {status === 'success' && !isSpeaking ? (
          <>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setIsModalOpen(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 px-3 py-1.5 text-xs font-medium text-[color:var(--hud-text)] transition-colors hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
              >
                <Clock className="size-3.5 text-[color:var(--hud-accent)]" strokeWidth={2} />
                <span>View History Ledger</span>
              </button>
            </div>
            {isModalOpen
              ? createPortal(
                  <HistoryLedgerModal onClose={() => setIsModalOpen(false)} />,
                  document.body,
                )
              : null}
          </>
        ) : null}
      </div>
    </section>
  )
}

export function BriefingPanel(props: BriefingPanelProps): ReactElement {
  return (
    <BriefingStream
      key={props.status === 'success' ? props.briefing : props.status}
      {...props}
    />
  )
}
