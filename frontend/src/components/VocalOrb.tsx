import { useId, type ReactElement } from 'react'

export interface VocalOrbProps {
  isSpeaking: boolean
  className?: string
}

export function VocalOrb({
  isSpeaking,
  className,
}: VocalOrbProps): ReactElement {
  const filterId = useId().replace(/:/g, '')
  const glowFilter = `url(#${filterId})`

  const svgClassName = [
    'overflow-visible fill-none',
    className ?? 'h-24 w-24',
  ].join(' ')

  const stasisClassName = [
    'transition-all duration-700 ease-in-out',
    isSpeaking ? 'scale-0 opacity-0' : 'scale-100 opacity-100',
  ].join(' ')

  const gyroActiveClassName = [
    'transition-all duration-700 ease-in-out origin-center',
    isSpeaking
      ? 'scale-100 opacity-100'
      : 'pointer-events-none scale-50 opacity-0',
  ].join(' ')

  const outerGyroClassName = [
    gyroActiveClassName,
    isSpeaking ? 'animate-gyro-clockwise stroke-amber-500/80' : 'stroke-amber-500/80',
  ].join(' ')

  const innerGyroClassName = [
    gyroActiveClassName,
    isSpeaking ? 'animate-gyro-counter stroke-amber-400/90' : 'stroke-amber-400/90',
  ].join(' ')

  const coreClassName = [
    'fill-amber-300 transition-all duration-700 ease-in-out origin-center',
    isSpeaking
      ? 'scale-150 opacity-100 drop-shadow-[0_0_8px_rgba(252,211,77,0.9)]'
      : 'scale-100 opacity-60',
  ].join(' ')

  return (
    <div className="flex items-center justify-center" aria-hidden="true">
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
            x1={isSpeaking ? 50 : 15}
            y1={50}
            x2={isSpeaking ? 50 : 85}
            y2={50}
            strokeWidth={2}
            strokeLinecap="round"
            className="stroke-neutral-500/50"
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
