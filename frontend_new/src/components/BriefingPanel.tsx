import {
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactElement,
} from 'react'

const WORD_REVEAL_INTERVAL_MS = 72

export type BriefingPanelProps = {
  briefing: string
}

function wordsFromPayload(source: string): string[] {
  const trimmed = source.trim()
  if (trimmed.length === 0) return []
  return trimmed.split(/\s+/).filter((segment) => segment.length > 0)
}

function BriefingStream({ briefing }: BriefingPanelProps): ReactElement {
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

export function BriefingPanel({ briefing }: BriefingPanelProps): ReactElement {
  return <BriefingStream key={briefing} briefing={briefing} />
}
