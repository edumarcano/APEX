import {
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactElement,
} from 'react'

import type { SystemState } from '../types/telemetry'

const WORD_REVEAL_INTERVAL_MS = 72

export type BriefingPanelProps = {
  briefing: string
  status: SystemState
  error: string | null
  isLoading: boolean
}

function wordsFromPayload(source: string): string[] {
  const trimmed = source.trim()
  if (trimmed.length === 0) return []
  return trimmed.split(/\s+/).filter((segment) => segment.length > 0)
}

function BriefingStream({
  briefing,
  status,
  error,
  isLoading,
}: BriefingPanelProps): ReactElement {
  const labelId = useId()
  const words = useMemo(() => wordsFromPayload(briefing), [briefing])
  const [visibleCount, setVisibleCount] = useState(0)

  const visibleText = useMemo(
    () => words.slice(0, visibleCount).join(' '),
    [words, visibleCount],
  )

  useEffect(() => {
    if (words.length === 0) {
      return undefined
    }

    let revealed = 0
    const intervalId = window.setInterval(() => {
      revealed += 1
      setVisibleCount(revealed)
      if (revealed >= words.length) {
        window.clearInterval(intervalId)
      }
    }, WORD_REVEAL_INTERVAL_MS)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [words])

  const showCaret = visibleCount < words.length

  if (isLoading || status === 'idle') {
    return (
      <section
        className="flex h-full min-h-56 flex-col justify-center rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)] md:min-h-72"
        aria-labelledby={labelId}
        aria-busy="true"
      >
        <h2
          id={labelId}
          className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
        >
          Core Briefing
        </h2>
        <p className="text-sm leading-relaxed text-[color:var(--hud-text)] opacity-80">
          Fetching briefing stream…
        </p>
      </section>
    )
  }

  if (status === 'error') {
    return (
      <section
        className="flex h-full min-h-56 flex-col justify-center rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)] md:min-h-72"
        aria-labelledby={labelId}
      >
        <h2
          id={labelId}
          className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
        >
          Core Briefing
        </h2>
        <p className="text-sm leading-relaxed text-[color:var(--hud-text)]">
          {error ?? 'Briefing unavailable.'}
        </p>
      </section>
    )
  }

  if (words.length === 0) {
    return (
      <section
        className="rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)]"
        aria-labelledby={labelId}
      >
        <h2
          id={labelId}
          className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
        >
          Briefing
        </h2>
        <p className="text-sm leading-relaxed text-[color:var(--hud-text)]">
          No briefing content.
        </p>
      </section>
    )
  }

  return (
    <section
      className="rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)]"
      aria-labelledby={labelId}
    >
      <h2
        id={labelId}
        className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
      >
        Briefing
      </h2>
      <div
        className="min-h-[4.5rem] whitespace-pre-wrap break-words text-sm leading-relaxed text-[color:var(--hud-text)]"
        aria-live="polite"
        aria-atomic="false"
      >
        {visibleText}
        {showCaret ? (
          <span
            className="ml-0.5 inline-block h-4 w-px translate-y-0.5 bg-[color:var(--hud-accent)] opacity-60 animate-pulse"
            aria-hidden
          />
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
