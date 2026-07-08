import { useId, type ReactElement } from 'react'

import type { TtsEngine } from '../types/telemetry'

export interface VoiceSignalGlyphProps {
  isSpeaking: boolean
  activeTtsEngine?: TtsEngine
  systemLoadThrottled?: boolean
  className?: string
}

const RIBS = [
  { d: 'M73 15 L58 21 L73 27', width: 1.8, delay: '0ms' },
  { d: 'M61 11 L42 21 L61 31', width: 1.5, delay: '120ms' },
  { d: 'M107 15 L122 21 L107 27', width: 1.8, delay: '60ms' },
  { d: 'M119 11 L138 21 L119 31', width: 1.5, delay: '180ms' },
] as const

export function VoiceSignalGlyph({
  isSpeaking,
  activeTtsEngine = 'google',
  systemLoadThrottled = false,
  className = '',
}: VoiceSignalGlyphProps): ReactElement {
  const filterId = useId().replace(/:/g, '')
  const goldGlow = `url(#${filterId})`

  return (
    <div
      className={['flex items-center justify-center', className].join(' ')}
      aria-hidden="true"
      data-slot="voice-signal-glyph"
      data-tts-engine={activeTtsEngine}
      data-throttled={systemLoadThrottled ? 'true' : 'false'}
    >
      <svg
        viewBox="0 0 180 42"
        className="h-10 w-40 overflow-visible fill-none sm:w-44"
      >
        <defs>
          <filter id={filterId} x="-35%" y="-80%" width="170%" height="260%">
            <feGaussianBlur stdDeviation="3.5" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <line
          x1={32}
          y1={21}
          x2={148}
          y2={21}
          strokeWidth={1}
          strokeLinecap="round"
          className="stroke-[#0F4DB8]/35"
        />

        {RIBS.map((rib) => (
          <path
            key={rib.d}
            d={rib.d}
            strokeWidth={rib.width}
            strokeLinecap="round"
            strokeLinejoin="round"
            filter={isSpeaking ? goldGlow : undefined}
            className={[
              'origin-center transition-all duration-500 ease-out',
              isSpeaking
                ? 'animate-voice-rib stroke-[#FBBF24]/90 opacity-100'
                : 'stroke-[#6EA8FF]/30 opacity-55',
            ].join(' ')}
            style={{
              animationDelay: rib.delay,
              transformBox: 'fill-box',
              transformOrigin: 'center',
            }}
          />
        ))}

        <path
          d="M82 13 L90 7 L98 13 L98 29 L90 35 L82 29 Z"
          filter={isSpeaking ? goldGlow : undefined}
          className={[
            'transition-all duration-700 ease-out',
            isSpeaking
              ? 'fill-[#FBBF24]/95 stroke-[#FFF3B0] drop-shadow-[0_0_12px_rgba(251,191,36,0.85)]'
              : 'fill-[#0F4DB8]/18 stroke-[#FBBF24]/45',
          ].join(' ')}
          strokeWidth={1.4}
        />
        <circle
          cx={90}
          cy={21}
          r={isSpeaking ? 3.8 : 2.6}
          className={[
            'transition-all duration-700 ease-out',
            isSpeaking ? 'animate-signal-breath fill-white' : 'fill-[#FBBF24]/55',
          ].join(' ')}
        />
      </svg>
    </div>
  )
}
