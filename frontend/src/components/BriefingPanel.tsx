import { useEffect, useId, useState, type ReactElement } from 'react'

import type { SystemState } from '../types/telemetry'

export type BriefingPanelProps = {
  briefing: string
  status: SystemState
  error: string | null
  isLoading: boolean
}

function sectionShellClassName(extra = ''): string {
  return [
    'rounded-2xl border border-[color:var(--hud-border-color)] p-[var(--hud-panel-pad)] hud-glass hover-warm-subtle',
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
}: BriefingPanelProps): ReactElement {
  const labelId = useId()
  const rawText = briefing.trim()
  const [revealed, setRevealed] = useState(false)

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
          'flex h-full min-h-56 flex-col justify-center md:min-h-72',
        )}
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
        className={sectionShellClassName(
          'flex h-full min-h-56 flex-col justify-center md:min-h-72',
        )}
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

  if (rawText.length === 0) {
    return (
      <section className={sectionShellClassName()} aria-labelledby={labelId}>
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
    <section className={sectionShellClassName()} aria-labelledby={labelId}>
      <h2
        id={labelId}
        className="mb-3 text-xs font-semibold uppercase tracking-widest text-[color:var(--hud-accent)] opacity-80"
      >
        Briefing
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
