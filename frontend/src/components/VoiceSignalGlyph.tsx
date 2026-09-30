import { useId, type ReactElement } from 'react'

import type { SystemState, TtsEngine } from '../types/telemetry'
import {
  resolveSignalState,
  resolveToneClasses,
  type LogoActivity,
} from '../lib/logoVisualState'

export interface VoiceSignalGlyphProps {
  status: SystemState
  activity?: LogoActivity
  isSpeaking: boolean
  activeTtsEngine?: TtsEngine
  systemLoadThrottled?: boolean
  isCortexQuerying?: boolean
  cortexActivityLabel?: string | null
  isLocalModelLoading?: boolean
  loadingDisplayName?: string | null
  isTelemetryCollecting?: boolean
  className?: string
  hideLabel?: boolean
}

/** Short rail segments that travel toward the center (left side). */
const FLOW_LEFT = [
  { x1: 34, x2: 44, delay: '0ms' },
  { x1: 48, x2: 58, delay: '180ms' },
  { x1: 62, x2: 72, delay: '360ms' },
] as const

/** Short rail segments that travel toward the center (right side). */
const FLOW_RIGHT = [
  { x1: 136, x2: 146, delay: '0ms' },
  { x1: 122, x2: 132, delay: '180ms' },
  { x1: 108, x2: 118, delay: '360ms' },
] as const

/** Waveform bar geometry: x center, base half-height, stagger delay. */
const WAVE_BARS = [
  { x: 78, halfH: 5, delay: '0ms' },
  { x: 84, halfH: 9, delay: '90ms' },
  { x: 90, halfH: 13, delay: '180ms' },
  { x: 96, halfH: 9, delay: '270ms' },
  { x: 102, halfH: 5, delay: '360ms' },
] as const

const RAIL_Y = 26

export function VoiceSignalGlyph({
  activity = null,
  isSpeaking,
  activeTtsEngine = 'google',
  systemLoadThrottled = false,
  isCortexQuerying = false,
  cortexActivityLabel = null,
  isLocalModelLoading = false,
  loadingDisplayName = null,
  isTelemetryCollecting = false,
  className = '',
  hideLabel = false,
}: VoiceSignalGlyphProps): ReactElement {
  const filterId = useId().replace(/:/g, '')
  const waveBlur = `url(#${filterId})`
  const signalState = resolveSignalState(
    activity,
    isLocalModelLoading,
    loadingDisplayName,
    isCortexQuerying,
    isTelemetryCollecting,
    cortexActivityLabel,
  )
  const toneClasses = resolveToneClasses(signalState.tone)
  const showFlow = signalState.isActive

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
      data-speaking={isSpeaking ? 'true' : 'false'}
    >
      <svg
        viewBox="0 0 180 52"
        className="h-11 w-40 overflow-visible fill-none sm:w-44"
      >
        <defs>
          <filter id={filterId} x="-50%" y="-80%" width="200%" height="260%">
            <feGaussianBlur stdDeviation="2.2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Stage-toned conduit rail — stays stage-colored while speaking */}
        <line
          x1={28}
          y1={RAIL_Y}
          x2={152}
          y2={RAIL_Y}
          strokeWidth={1.1}
          strokeLinecap="round"
          className={[
            'transition-colors duration-700 ease-out',
            toneClasses.rail,
          ].join(' ')}
        />

        {/* Thinking flow: mirrored dashes traveling toward center */}
        {showFlow &&
          FLOW_LEFT.map((seg) => (
            <line
              key={`L-${seg.x1}`}
              x1={seg.x1}
              y1={RAIL_Y}
              x2={seg.x2}
              y2={RAIL_Y}
              strokeWidth={2}
              strokeLinecap="round"
              className={[
                'animate-signal-flow-left transition-opacity duration-500 ease-out',
                toneClasses.accent,
                isSpeaking ? 'opacity-55' : 'opacity-100',
              ].join(' ')}
              style={{
                animationDelay: seg.delay,
                transformBox: 'fill-box',
                transformOrigin: 'center',
              }}
            />
          ))}

        {showFlow &&
          FLOW_RIGHT.map((seg) => (
            <line
              key={`R-${seg.x1}`}
              x1={seg.x1}
              y1={RAIL_Y}
              x2={seg.x2}
              y2={RAIL_Y}
              strokeWidth={2}
              strokeLinecap="round"
              className={[
                'animate-signal-flow-right transition-opacity duration-500 ease-out',
                toneClasses.accent,
                isSpeaking ? 'opacity-55' : 'opacity-100',
              ].join(' ')}
              style={{
                animationDelay: seg.delay,
                transformBox: 'fill-box',
                transformOrigin: 'center',
              }}
            />
          ))}

        {/* Center: stage node when quiet; cyan waveform when speaking */}
        {isSpeaking ? (
          <g filter={waveBlur}>
            {/* Stage-colored aperture ring behind waveform */}
            <circle
              cx={90}
              cy={RAIL_Y}
              r={16}
              strokeWidth={1.2}
              className={[
                'fill-transparent transition-colors duration-500 ease-out',
                toneClasses.nodeRing,
              ].join(' ')}
            />
            {WAVE_BARS.map((bar) => (
              <rect
                key={bar.x}
                x={bar.x - 1.6}
                y={RAIL_Y - bar.halfH}
                width={3.2}
                height={bar.halfH * 2}
                rx={1.4}
                className="animate-speech-wave-bar fill-[#22D3EE]/90 stroke-[#A5F3FC]/95 drop-shadow-[0_0_8px_rgba(34,211,238,0.85)]"
                style={{
                  animationDelay: bar.delay,
                  transformBox: 'fill-box',
                  transformOrigin: 'center',
                }}
              />
            ))}
          </g>
        ) : (
          <path
            d="M90 16 L100 26 L90 36 L80 26 Z"
            strokeWidth={1.4}
            className={[
              'transition-all duration-500 ease-out',
              toneClasses.aperture,
            ].join(' ')}
          />
        )}
      </svg>
      {!hideLabel ? (
        <span
          className={[
            'font-orbitron text-[9px] font-semibold uppercase tracking-[0.2em] transition-colors duration-700 sm:text-[10px]',
            toneClasses.label,
          ].join(' ')}
        >
          {signalState.label}
        </span>
      ) : null}
    </div>
  )
}
