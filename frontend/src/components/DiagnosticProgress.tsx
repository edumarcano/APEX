import type { ReactElement } from 'react'

import type { PipelineState } from '../types/telemetry'

const PIPELINE_STEPS = [
  { step: 1, label: 'Gate' },
  { step: 2, label: 'Collection' },
  { step: 3, label: 'Synthesis' },
  { step: 4, label: 'Delivery' },
] as const

export type DiagnosticProgressProps = {
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
  isTriggerLoading: boolean
}

export function DiagnosticProgress({
  pipelineState,
  isPipelinePolling,
  isTriggerLoading,
}: DiagnosticProgressProps): ReactElement {
  const activeStep = pipelineState?.step ?? 0
  const isTracking = isPipelinePolling || isTriggerLoading

  return (
    <nav
      className="w-full"
      aria-label="Pipeline diagnostic progress"
      aria-busy={isTracking}
      data-slot="diagnostic-progress"
    >
      <ol className="m-0 flex w-full list-none items-start justify-between gap-1 p-0">
        {PIPELINE_STEPS.map(({ step, label }, index) => {
          const isActive = activeStep === step
          const isPast = activeStep > step
          const showConnector = index < PIPELINE_STEPS.length - 1

          const nodeClassName = [
            'flex size-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors',
            isActive
              ? 'border-[color:var(--hud-accent)] bg-[color:var(--hud-accent)] text-[color:var(--hud-bg)]'
              : isPast
                ? 'border-[color:var(--hud-text)] text-[color:var(--hud-text)] opacity-80'
                : 'border-[color:var(--hud-border-color)] text-[color:var(--hud-text)] opacity-35',
          ].join(' ')

          const labelClassName = [
            'mt-2 text-center text-xs font-medium uppercase tracking-wide transition-colors',
            isActive
              ? 'text-[color:var(--hud-accent)]'
              : isPast
                ? 'text-[color:var(--hud-text)] opacity-70'
                : 'text-[color:var(--hud-text)] opacity-35',
          ].join(' ')

          return (
            <li
              key={step}
              className="flex min-w-0 flex-1 flex-col items-center"
              aria-current={isActive ? 'step' : undefined}
            >
              <div className="flex w-full items-center">
                <span className={nodeClassName} aria-hidden>
                  {step}
                </span>
                {showConnector ? (
                  <span
                    className={[
                      'mx-1 h-0.5 min-w-2 flex-1 rounded-full transition-colors',
                      isPast || isActive
                        ? 'bg-[color:var(--hud-text)] opacity-50'
                        : 'bg-[color:var(--hud-border-color)] opacity-60',
                    ].join(' ')}
                    aria-hidden
                  />
                ) : null}
              </div>
              <span className={labelClassName}>{label}</span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
