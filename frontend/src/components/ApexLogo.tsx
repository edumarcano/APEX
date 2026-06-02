import { useEffect, useState, type ReactElement } from 'react'
import type { SystemState } from '../types/telemetry'

export interface ApexLogoProps {
  step: number | null
  status: SystemState
  /** Increment this integer when a reminder successfully POSTs to trigger the pulse */
  reminderPulseCount?: number
  className?: string
}

export function ApexLogo({
  step,
  status,
  reminderPulseCount = 0,
  className = '',
}: ApexLogoProps): ReactElement {
  const [pulseActive, setPulseActive] = useState(false)

  // Trigger the 800ms brightness surge when a reminder is saved
  useEffect(() => {
    if (reminderPulseCount > 0) {
      setPulseActive(true)
      const timer = window.setTimeout(() => setPulseActive(false), 800)
      return () => window.clearTimeout(timer)
    }
  }, [reminderPulseCount])

  const isError = status === 'error'
  const activeStep = step ?? 0
  const isBreathing = activeStep >= 4

  
  // Base colors with Error State Override (#ff4444)
  const baseBlue = isError ? 'fill-red-500' : 'fill-blue-900'
  const activeBlue = isError ? 'fill-red-400' : 'fill-blue-500 drop-shadow-[0_0_8px_rgba(59,130,246,0.8)]'
  
  const baseGold = isError ? 'fill-red-500' : 'fill-amber-500'
  const pulseGold = isError ? 'fill-red-400' : 'fill-amber-300 drop-shadow-[0_0_12px_rgba(252,211,77,1)]'
  
  // Staggered Pipeline Illuminations
  const getSegmentClass = (segmentStep: number) => {
    return `transition-all duration-700 ease-in-out ${
      activeStep >= segmentStep ? activeBlue : baseBlue
    }`
  }

  // Core Animation States
  const coreAnimation = isBreathing && !isError 
    ? 'animate-[pulse_3s_ease-in-out_infinite]' 
    : ''
    
  const trunkPulse = pulseActive && !isError
    ? pulseGold
    : baseGold

  return (
    <div className={`relative flex items-center justify-center ${className}`} aria-hidden="true">
      <svg 
        viewBox="0 0 100 100" 
        className="h-full w-full overflow-visible"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* =========================================
            OUTER SHELL (BLUE SEGMENTS)
        ========================================= */}
        
        {/* Stage 4: Crown */}
        <g id="apex-crown" className={getSegmentClass(4)}>
          <path d="M 50 0 L 38 24 C 42 23 45 22 46.5 21 L 43 21 L 50 3 L 57 21 L 53.5 21 C 55 22 58 23 62 24 Z" />
        </g>

        {/* Stage 3: Upper Roots */}
        <g id="apex-upper-roots" className={getSegmentClass(3)}>
          <path d="M 35 28 L 26 48 C 36 46 41 45 44 43 C 44 38 41 33 28 27 C 31 27 33 27 35 28 Z" />
          <path d="M 65 28 L 74 48 C 64 46 59 45 56 43 C 56 38 59 33 72 27 C 69 27 67 27 65 28 Z" />
        </g>

        {/* Stage 2: Lower Roots */}
        <g id="apex-lower-roots" className={getSegmentClass(2)}>
          <path d="M 23 52 L 13 76 C 26 73 35 72 41 68 C 42 61 38 56 16 52 C 18 52 20 52 23 52 Z" />
          <path d="M 77 52 L 87 76 C 74 73 65 72 59 68 C 58 61 62 56 84 52 C 82 52 80 52 77 52 Z" />
        </g>

        {/* Stage 1: Trunk Base */}
        <g id="apex-trunk" className={getSegmentClass(1)}>
          <path d="M 10 80 L 2 97 L 18 97 C 28 92 36 86 42 74 C 34 76 22 78 10 80 Z" />
          <path d="M 90 80 L 98 97 L 82 97 C 72 92 64 86 58 74 C 66 76 78 78 90 80 Z" />
        </g>

        {/* =========================================
            INNER CORE (GOLD XYLEM NETWORK)
        ========================================= */}
        <path
          id="apex-gold-core"
          className={`transition-all duration-500 ease-in-out ${trunkPulse} ${coreAnimation}`}
          d="M 50 5 L 42 20 L 47 20 C 47 20 38 25 30 25 C 40 25 46 32 46 40 C 46 40 32 50 18 50 C 32 50 44 60 44 70 C 44 85 30 95 20 95 L 80 95 C 70 95 56 85 56 70 C 56 60 68 50 82 50 C 68 50 54 40 54 40 C 54 32 60 25 70 25 C 62 25 53 20 53 20 L 58 20 Z"
        />
      </svg>
    </div>
  )
}