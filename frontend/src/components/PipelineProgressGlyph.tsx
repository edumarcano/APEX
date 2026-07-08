import { type ReactElement } from 'react'

import type { SystemState } from '../types/telemetry'

export interface PipelineProgressGlyphProps {
  step: number | null
  status: SystemState
  isSpeaking: boolean
  className?: string
}

const NODE_POSITIONS = [
  { cx: 18, cy: 30 },
  { cx: 58, cy: 14 },
  { cx: 98, cy: 30 },
  { cx: 138, cy: 14 },
] as const

function resolveNodeClass(index: number, activeStep: number): string {
  if (activeStep < index) {
    return 'fill-[#0F4DB8]/35 stroke-[#6EA8FF]/25'
  }

  if (index === 3 && activeStep >= 3) {
    return 'fill-[#A855F7] stroke-[#D8B4FE] drop-shadow-[0_0_8px_rgba(168,85,247,0.9)]'
  }

  if (index === 4 && activeStep >= 4) {
    return 'fill-[#FBBF24] stroke-[#FFF3B0] drop-shadow-[0_0_8px_rgba(251,191,36,0.9)]'
  }

  return 'fill-[#39FF88] stroke-[#D1FAE5] drop-shadow-[0_0_8px_rgba(57,255,136,0.8)]'
}

export function PipelineProgressGlyph({
  step,
  status,
  isSpeaking,
  className = '',
}: PipelineProgressGlyphProps): ReactElement {
  const activeStep = step ?? 0
  const isVisible = status === 'loading' && activeStep >= 1 && activeStep <= 3 && !isSpeaking

  return (
    <div
      className={[
        'flex max-h-0 items-center justify-center overflow-hidden opacity-0 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]',
        isVisible ? 'max-h-8 opacity-100' : '',
        className,
      ].join(' ')}
      aria-hidden="true"
      data-slot="pipeline-progress-glyph"
    >
      <svg
        viewBox="0 0 156 44"
        className="h-8 w-36 overflow-visible fill-none sm:w-40"
      >
        <path
          d="M18 30 C36 30 40 14 58 14 C76 14 80 30 98 30 C116 30 120 14 138 14"
          strokeWidth={1.6}
          strokeLinecap="round"
          className="stroke-[#0F4DB8]/45"
        />
        <path
          d="M18 30 C36 30 40 14 58 14 C76 14 80 30 98 30 C116 30 120 14 138 14"
          strokeWidth={2.4}
          strokeLinecap="round"
          strokeDasharray="18 118"
          className={
            activeStep >= 3
              ? 'animate-pipeline-flow stroke-[#A855F7]/85'
              : 'animate-pipeline-flow stroke-[#39FF88]/85'
          }
        />
        {NODE_POSITIONS.map((node, index) => {
          const nodeStep = index + 1
          const isActiveNode = activeStep === nodeStep

          return (
            <g key={`${node.cx}-${node.cy}`}>
              <circle
                cx={node.cx}
                cy={node.cy}
                r={isActiveNode ? 7 : 5}
                strokeWidth={1.2}
                className={[
                  'transition-all duration-500 ease-out',
                  resolveNodeClass(nodeStep, activeStep),
                  isActiveNode ? 'animate-signal-breath' : '',
                ].join(' ')}
              />
              <circle
                cx={node.cx}
                cy={node.cy}
                r={1.5}
                className={activeStep >= nodeStep ? 'fill-white/90' : 'fill-[#6EA8FF]/35'}
              />
            </g>
          )
        })}
      </svg>
    </div>
  )
}
