import { AlertTriangle, ShieldAlert, X } from 'lucide-react'
import { forwardRef, useEffect, useRef, type MouseEvent, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import type { PreflightDialogProps } from '../hooks/usePreflight'
import { useFocusTrap } from '../hooks/useFocusTrap'

export type { PreflightDialogChoice, PreflightDialogProps } from '../hooks/usePreflight'

export function PreflightDialog(props: PreflightDialogProps): ReactElement | null {
  const { open, warnings, blockers, isChecking, error, onChoice } = props
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const hasBlockers = blockers.length > 0

  useFocusTrap(open, dialogRef)

  useEffect(() => {
    if (!open) return undefined

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onChoice('cancel')
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, onChoice])

  if (!open) {
    return null
  }

  const handleBackdropClick = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === event.currentTarget) {
      onChoice('cancel')
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-md transition-opacity duration-300"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="relative rounded-2xl border border-white/10 hud-glass max-w-lg w-full max-h-[80vh] flex flex-col p-6 shadow-2xl transition-all duration-300"
        role="dialog"
        aria-modal="true"
        aria-labelledby="preflight-dialog-title"
        tabIndex={-1}
      >
        <header className="mb-4 flex shrink-0 items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <span className="hud-icon-badge size-7 shrink-0">
              {hasBlockers ? (
                <ShieldAlert className="size-4 text-red-400" strokeWidth={1.75} aria-hidden />
              ) : (
                <AlertTriangle className="size-4 text-[#FBBF24]" strokeWidth={1.75} aria-hidden />
              )}
            </span>
            <h2
              id="preflight-dialog-title"
              className="font-orbitron text-sm font-semibold tracking-[0.12em] text-[color:var(--hud-text)]"
            >
              {hasBlockers ? 'Activation Blocked' : 'Preflight Advisory'}
            </h2>
          </div>
          <button
            type="button"
            onClick={() => onChoice('cancel')}
            className="inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 p-1.5 text-[color:var(--hud-text)] transition-colors hover:bg-white/10 hover:border-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label="Close preflight dialog"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </header>

        <div className="overflow-y-auto space-y-3 pr-1 scrollbar-thin flex-1 min-h-0">
          {error ? (
            <p className="text-sm leading-relaxed text-red-400">{error}</p>
          ) : null}

          {hasBlockers ? (
            <ul className="space-y-2">
              {blockers.map((blocker) => (
                <li
                  key={blocker.code}
                  className="flex items-start gap-2.5 rounded-xl border border-red-500/20 bg-red-500/5 p-3 text-sm leading-relaxed text-[color:var(--hud-text)]"
                >
                  <ShieldAlert className="mt-0.5 size-4 shrink-0 text-red-400" strokeWidth={2} aria-hidden />
                  <span>{blocker.message}</span>
                </li>
              ))}
            </ul>
          ) : null}

          {warnings.length > 0 ? (
            <ul className="space-y-2">
              {warnings.map((warning) => (
                <li
                  key={warning.code}
                  className="flex items-start gap-2.5 rounded-xl border border-[#FBBF24]/20 bg-[#FBBF24]/5 p-3 text-sm leading-relaxed text-[color:var(--hud-text)]"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[#FBBF24]" strokeWidth={2} aria-hidden />
                  <span>{warning.message}</span>
                </li>
              ))}
            </ul>
          ) : null}

          {!hasBlockers && warnings.length === 0 && !error ? (
            <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">
              No advisories to review.
            </p>
          ) : null}
        </div>

        <div className="mt-5 flex shrink-0 flex-wrap justify-end gap-2">
          {hasBlockers ? (
            <DialogButton onClick={() => onChoice('cancel')} variant="primary">
              Close
            </DialogButton>
          ) : (
            <>
              <DialogButton onClick={() => onChoice('cancel')} variant="ghost" disabled={isChecking}>
                Cancel
              </DialogButton>
              <DialogButton onClick={() => onChoice('continue_once')} variant="ghost" disabled={isChecking}>
                Continue once
              </DialogButton>
              <DialogButton
                onClick={() => onChoice('continue_session')}
                variant="primary"
                disabled={isChecking}
              >
                Continue for this session
              </DialogButton>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

interface DialogButtonProps {
  onClick: () => void
  variant: 'primary' | 'ghost'
  disabled?: boolean
  children: ReactNode
}

const DialogButton = forwardRef<HTMLButtonElement, DialogButtonProps>(
  ({ onClick, variant, disabled = false, children }, ref): ReactElement => (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center rounded-lg border px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] ${
        variant === 'primary'
          ? 'border-[#0F4DB8]/40 bg-[#0F4DB8]/10 text-[#FBBF24] hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15'
          : 'border-white/10 bg-white/5 text-[color:var(--hud-text)] hover:border-white/20 hover:bg-white/10'
      } disabled:cursor-not-allowed disabled:opacity-40`}
    >
      {children}
    </button>
  ),
)
DialogButton.displayName = 'DialogButton'
