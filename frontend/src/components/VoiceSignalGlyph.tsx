import { useId, type ReactElement } from 'react'

import type { SystemState, TtsEngine } from '../types/telemetry'

export interface VoiceSignalGlyphProps {
  step: number | null
  status: SystemState
  isSpeaking: boolean
  activeTtsEngine?: TtsEngine
  systemLoadThrottled?: boolean
  className?: string
}

type SignalTone = 'standby' | 'emerald' | 'purple' | 'gold'

interface SignalState {
  label: string
  tone: SignalTone
  isActive: boolean
}

const SIDE_ARROWS = [
  { d: 'M72 15 L54 24 L72 33', delay: '0ms' },
  { d: 'M58 12 L32 24 L58 36', delay: '140ms' },
  { d: 'M108 15 L126 24 L108 33', delay: '70ms' },
  { d: 'M122 12 L148 24 L122 36', delay: '210ms' },
] as const

function resolveSignalState(step: number | null, status: SystemState): SignalState {
  if (step === 4) {
    return { label: 'Delivering', tone: 'gold', isActive: true }
  }

  if (status === 'loading' && step === 3) {
    return { label: 'Synthesizing', tone: 'purple', isActive: true }
  }

  if (status === 'loading' && step === 2) {
    return { label: 'Collecting Data', tone: 'emerald', isActive: true }
  }

  if (status === 'loading' && step === 1) {
    return { label: 'Processing', tone: 'emerald', isActive: true }
  }

  return { label: 'Standby', tone: 'standby', isActive: false }
}

function resolveToneClasses(tone: SignalTone): {
  accent: string
  aperture: string
  label: string
  rail: string
} {
  if (tone === 'gold') {
    return {
      accent: 'stroke-[#FBBF24]/90',
      aperture: 'fill-[#FBBF24]/88 stroke-[#FFF3B0]/90 drop-shadow-[0_0_10px_rgba(251,191,36,0.75)]',
      label: 'text-[#FBBF24]',
      rail: 'stroke-[#FBBF24]/35',
    }
  }

  if (tone === 'purple') {
    return {
      accent: 'stroke-[#A855F7]/90',
      aperture: 'fill-[#A855F7]/82 stroke-[#D8B4FE]/80 drop-shadow-[0_0_10px_rgba(168,85,247,0.72)]',
      label: 'text-[#C084FC]',
      rail: 'stroke-[#A855F7]/35',
    }
  }

  if (tone === 'emerald') {
    return {
      accent: 'stroke-[#39FF88]/90',
      aperture: 'fill-[#39FF88]/78 stroke-[#D1FAE5]/80 drop-shadow-[0_0_10px_rgba(57,255,136,0.68)]',
      label: 'text-[#6EE7B7]',
      rail: 'stroke-[#39FF88]/32',
    }
  }

  return {
    accent: 'stroke-[#6EA8FF]/28',
    aperture: 'fill-[#0F4DB8]/18 stroke-[#6EA8FF]/28',
    label: 'text-[#6EA8FF]/45',
    rail: 'stroke-[#0F4DB8]/28',
  }
}

export function VoiceSignalGlyph({
  step,
  status,
  isSpeaking,
  activeTtsEngine = 'google',
  systemLoadThrottled = false,
  className = '',
}: VoiceSignalGlyphProps): ReactElement {
  const filterId = useId().replace(/:/g, '')
  const cyanPulse = `url(#${filterId})`
  const signalState = resolveSignalState(step, status)
  const toneClasses = resolveToneClasses(signalState.tone)

  return (
    <div
      className={[
        'flex flex-col items-center justify-center gap-1 transition-opacity duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]',
        signalState.isActive ? 'opacity-100' : 'opacity-55',
        className,
      ].join(' ')}
      aria-hidden="true"
      data-slot="voice-signal-glyph"
      data-signal-tone={signalState.tone}
      data-tts-engine={activeTtsEngine}
      data-throttled={systemLoadThrottled ? 'true' : 'false'}
    >
      <svg
        viewBox="0 0 180 52"
        className="h-11 w-40 overflow-visible fill-none sm:w-44"
      >
        <defs>
          <filter id={filterId} x="-40%" y="-80%" width="180%" height="260%">
            <feGaussianBlur stdDeviation="3.5" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <line
          x1={28}
          y1={26}
          x2={152}
          y2={26}
          strokeWidth={1.1}
          strokeLinecap="round"
          className={[
            'transition-colors duration-700 ease-out',
            toneClasses.rail,
          ].join(' ')}
        />

        {SIDE_ARROWS.map((arrow) => (
          <path
            key={arrow.d}
            d={arrow.d}
            strokeWidth={1.7}
            strokeLinecap="round"
            strokeLinejoin="round"
            className={[
              'origin-center transition-all duration-700 ease-out',
              signalState.isActive ? 'animate-thinking-arrow' : '',
              toneClasses.accent,
            ].join(' ')}
            style={{
              animationDelay: arrow.delay,
              transformBox: 'fill-box',
              transformOrigin: 'center',
            }}
          />
        ))}

        <path
          d="M79 17 L90 9 L101 17 L101 35 L90 43 L79 35 Z"
          filter={isSpeaking ? cyanPulse : undefined}
          strokeWidth={1.5}
          className={[
            'transition-all duration-500 ease-out',
            isSpeaking
              ? 'animate-speech-core-pulse fill-[#22D3EE]/85 stroke-[#A5F3FC]/95 drop-shadow-[0_0_14px_rgba(34,211,238,0.9)]'
              : toneClasses.aperture,
          ].join(' ')}
        />
      </svg>
      <span
        className={[
          'font-mono text-[9px] font-semibold uppercase tracking-[0.22em] transition-colors duration-700 sm:text-[10px]',
          toneClasses.label,
        ].join(' ')}
      >
        {signalState.label}
      </span>
    </div>
  )
}
