import { useId, type ReactElement } from 'react'

import type { TtsEngine } from '../types/telemetry'

export interface VocalOrbProps {
  isSpeaking: boolean
  activeTtsEngine?: TtsEngine
  systemLoadThrottled?: boolean
  className?: string
}

export function VocalOrb({
  isSpeaking,
  activeTtsEngine = 'google',
  systemLoadThrottled = false,
  className,
}: VocalOrbProps): ReactElement {
  const filterId = useId().replace(/:/g, '')
  const glowFilter = `url(#${filterId})`

  const isLocalEngine =
    activeTtsEngine === 'piper' || activeTtsEngine === 'pyttsx3'

  const svgClassName = [
    'overflow-visible fill-none',
    className ?? 'h-24 w-24',
  ].join(' ')

  const stasisClassName = [
    'transition-all duration-700 ease-in-out origin-center',
    isSpeaking
      ? isLocalEngine
        ? 'scale-150 opacity-100'
        : 'scale-0 opacity-0'
      : 'scale-100 opacity-100',
  ].join(' ')

  const gyroActiveClassName = [
    'transition-all duration-700 ease-in-out origin-center',
    isSpeaking
      ? 'scale-100 opacity-100'
      : 'pointer-events-none scale-50 opacity-0',
  ].join(' ')

  const outerGyroClassName = [
    gyroActiveClassName,
    isLocalEngine
      ? isSpeaking
        ? 'animate-gyro-clockwise stroke-cyan-400/80'
        : 'stroke-cyan-400/80'
      : isSpeaking
        ? 'animate-gyro-clockwise stroke-[#FBBF24]/80'
        : 'stroke-[#FBBF24]/80',
  ].join(' ')

  const innerGyroClassName = [
    gyroActiveClassName,
    isLocalEngine
      ? isSpeaking
        ? 'animate-gyro-counter stroke-cyan-500/90'
        : 'stroke-cyan-500/90'
      : isSpeaking
        ? 'animate-gyro-counter stroke-[#FBBF24]/90'
        : 'stroke-[#FBBF24]/90',
  ].join(' ')

  const coreClassName = [
    'transition-all duration-700 ease-in-out origin-center',
    isLocalEngine
      ? 'fill-cyan-400'
      : 'fill-[#FBBF24]',
    isSpeaking
      ? isLocalEngine
        ? 'scale-150 opacity-100 drop-shadow-[0_0_8px_rgba(34,211,238,0.9)]'
        : 'scale-150 opacity-100 drop-shadow-[0_0_8px_rgba(251,191,36,0.9)]'
      : 'scale-100 opacity-60',
  ].join(' ')

  const lineX1 = isLocalEngine
    ? isSpeaking
      ? 10
      : 50
    : isSpeaking
      ? 50
      : 15
  const lineX2 = isLocalEngine
    ? isSpeaking
      ? 90
      : 50
    : isSpeaking
      ? 50
      : 85

  return (
    <div
      className="flex items-center justify-center"
      aria-hidden="true"
      data-tts-engine={activeTtsEngine}
      data-throttled={systemLoadThrottled ? 'true' : 'false'}
    >
      <svg
        viewBox="0 0 100 100"
        className={svgClassName}
      >
        <defs>
          <filter id={filterId} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g
          className={stasisClassName}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        >
          <line
            x1={lineX1}
            y1={50}
            x2={lineX2}
            y2={50}
            strokeWidth={2}
            strokeLinecap="round"
            className={
              isLocalEngine
                ? 'stroke-cyan-400/60'
                : 'stroke-zinc-600/50'
            }
          />
        </g>

        <circle
          cx={50}
          cy={50}
          r={35}
          strokeWidth={2}
          strokeDasharray="40 15 20 15"
          filter={isSpeaking ? glowFilter : undefined}
          className={outerGyroClassName}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        />

        <circle
          cx={50}
          cy={50}
          r={22}
          strokeWidth={2}
          strokeDasharray="25 10 15 10"
          filter={isSpeaking ? glowFilter : undefined}
          className={innerGyroClassName}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        />

        <circle
          cx={50}
          cy={50}
          r={4}
          className={coreClassName}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        />
      </svg>
    </div>
  )
}
