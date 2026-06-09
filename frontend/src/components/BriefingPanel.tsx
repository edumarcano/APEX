import { Clock } from 'lucide-react'
import { useEffect, useId, useState, type ReactElement } from 'react'

import type { SystemState } from '../types/telemetry'

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
            {isModalOpen ? (
              <p className="mt-2 text-right text-xs text-[color:var(--hud-accent)]">
                Modal Doorway Open
              </p>
            ) : null}
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
