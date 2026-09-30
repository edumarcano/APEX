import type { BriefingVisualActivity } from './briefingVisualState'
import type { SystemState } from '../types/telemetry'

export type LogoActivity = BriefingVisualActivity | 'speech_preparing' | 'speech_playing' | null
export type OuterShellActivity = 'normal' | 'wave' | 'local_loading'

export interface LogoVisualStateInput {
  activity: LogoActivity
  briefingStatus: SystemState
  isCortexQuerying: boolean
  isLocalModelLoading: boolean
  isLocalModelLoaded: boolean
  isSpeaking: boolean
  isTelemetryCollecting: boolean
}

const COLORS = {
  blue: '15, 77, 184',
  gold: '251, 191, 36',
  green: '57, 255, 136',
  purple: '168, 85, 247',
  cyan: '34, 211, 238',
  red: '220, 38, 38',
  rust: '249, 115, 22',
} as const

export function resolveOuterShellActivity({
  activity,
  isLocalModelLoading,
  isTelemetryCollecting,
}: Pick<LogoVisualStateInput, 'activity' | 'isLocalModelLoading' | 'isTelemetryCollecting'>): OuterShellActivity {
  if (isLocalModelLoading) return 'local_loading'
  if (activity === 'investigating' || activity === 'speech_playing') return 'normal'
  if (
    activity === 'preparing' ||
    activity === 'collecting' ||
    activity === 'selecting' ||
    activity === 'synthesizing' ||
    activity === 'persisting' ||
    activity === 'speech_preparing' ||
    (!activity && isTelemetryCollecting)
  ) {
    return 'wave'
  }
  if (isTelemetryCollecting) return 'wave'
  return 'normal'
}

function activityColor(activity: LogoActivity): string | null {
  switch (activity) {
    case 'preparing':
    case 'collecting':
    case 'selecting':
      return COLORS.green
    case 'investigating':
    case 'synthesizing':
    case 'speech_preparing':
      return COLORS.purple
    case 'persisting':
      return COLORS.gold
    case 'briefing_ready':
      return COLORS.blue
    case 'speech_playing':
      return COLORS.cyan
    default:
      return null
  }
}

export function resolveLogoVisualColors(input: LogoVisualStateInput): {
  atmosphere: string
  logo: string
} {
  if (input.isLocalModelLoading || input.isLocalModelLoaded) {
    return { atmosphere: COLORS.rust, logo: COLORS.rust }
  }
  const activeColor = activityColor(input.activity)
  const atmosphere = input.activity !== 'briefing_ready' && activeColor !== null
    ? activeColor
    : input.isCortexQuerying
      ? COLORS.purple
      : input.activity === 'briefing_ready' && input.isTelemetryCollecting
        ? COLORS.green
        : input.activity === 'briefing_ready'
          ? COLORS.blue
          : input.isSpeaking
            ? COLORS.cyan
            : input.isTelemetryCollecting
              ? COLORS.green
              : input.briefingStatus === 'error'
                ? COLORS.red
                : COLORS.blue
  return {
    atmosphere,
    logo: atmosphere,
  }
}

export type SignalTone = 'standby' | 'emerald' | 'purple' | 'gold' | 'rust' | 'cyan'

export interface SignalState {
  label: string
  tone: SignalTone
  isActive: boolean
}

export function resolveSignalState(
  activity: LogoActivity = null,
  isLocalModelLoading: boolean = false,
  loadingDisplayName: string | null = null,
  isCortexQuerying: boolean = false,
  isTelemetryCollecting: boolean = false,
  cortexActivityLabel: string | null = null,
): SignalState {
  if (isLocalModelLoading) {
    const name = loadingDisplayName?.trim() || 'local model'
    return {
      label: `Loading ${name}`,
      tone: 'rust',
      isActive: true,
    }
  }

  if (activity && !(activity === 'briefing_ready' && (isCortexQuerying || isTelemetryCollecting))) {
    const signals: Partial<Record<NonNullable<LogoActivity>, SignalState>> = {
      preparing: { label: 'Preparing briefing', tone: 'emerald', isActive: true },
      collecting: { label: 'Collecting data', tone: 'emerald', isActive: true },
      selecting: { label: 'Selecting evidence', tone: 'emerald', isActive: true },
      investigating: { label: 'Investigating', tone: 'purple', isActive: true },
      synthesizing: { label: 'Synthesizing', tone: 'purple', isActive: true },
      persisting: { label: 'Saving briefing', tone: 'gold', isActive: true },
      briefing_ready: { label: 'Briefing ready', tone: 'gold', isActive: false },
      speech_preparing: { label: 'Preparing highlights', tone: 'purple', isActive: true },
      speech_playing: { label: 'Playing highlights', tone: 'cyan', isActive: true },
    }
    const signal = signals[activity]
    if (signal) return signal
  }

  if (isCortexQuerying) {
    return { label: cortexActivityLabel?.trim() || 'Preparing request', tone: 'purple', isActive: true }
  }

  if (isTelemetryCollecting) {
    return { label: 'Collecting telemetry', tone: 'emerald', isActive: true }
  }

  return { label: 'Ready', tone: 'standby', isActive: false }
}

export function resolveToneClasses(tone: SignalTone): {
  accent: string
  aperture: string
  label: string
  rail: string
  nodeRing: string
} {
  if (tone === 'gold') {
    return {
      accent: 'stroke-[#FBBF24]/90',
      aperture: 'fill-[#FBBF24]/88 stroke-[#FFF3B0]/90 drop-shadow-[0_0_10px_rgba(251,191,36,0.75)]',
      label: 'text-[#FBBF24]',
      rail: 'stroke-[#FBBF24]/35',
      nodeRing: 'stroke-[#FFF3B0]/70',
    }
  }

  if (tone === 'cyan') {
    return {
      accent: 'stroke-[#22D3EE]/90',
      aperture: 'fill-[#22D3EE]/82 stroke-[#A5F3FC]/80 drop-shadow-[0_0_10px_rgba(34,211,238,0.72)]',
      label: 'text-[#67E8F9]',
      rail: 'stroke-[#22D3EE]/35',
      nodeRing: 'stroke-[#A5F3FC]/65',
    }
  }

  if (tone === 'purple') {
    return {
      accent: 'stroke-[#A855F7]/90',
      aperture: 'fill-[#A855F7]/82 stroke-[#D8B4FE]/80 drop-shadow-[0_0_10px_rgba(168,85,247,0.72)]',
      label: 'text-[#C084FC]',
      rail: 'stroke-[#A855F7]/35',
      nodeRing: 'stroke-[#D8B4FE]/65',
    }
  }

  if (tone === 'emerald') {
    return {
      accent: 'stroke-[#39FF88]/90',
      aperture: 'fill-[#39FF88]/78 stroke-[#D1FAE5]/80 drop-shadow-[0_0_10px_rgba(57,255,136,0.68)]',
      label: 'text-[#6EE7B7]',
      rail: 'stroke-[#39FF88]/32',
      nodeRing: 'stroke-[#D1FAE5]/60',
    }
  }

  if (tone === 'rust') {
    return {
      accent: 'stroke-[#F97316]/90',
      aperture: 'fill-[#F97316]/82 stroke-[#FDBA74]/80 drop-shadow-[0_0_10px_rgba(249,115,22,0.72)]',
      label: 'text-[#FB923C]',
      rail: 'stroke-[#F97316]/35',
      nodeRing: 'stroke-[#FDBA74]/65',
    }
  }

  return {
    accent: 'stroke-[#6EA8FF]/28',
    aperture: 'fill-[#0F4DB8]/18 stroke-[#6EA8FF]/28',
    label: 'text-[#6EA8FF]/45',
    rail: 'stroke-[#0F4DB8]/28',
    nodeRing: 'stroke-[#6EA8FF]/25',
  }
}
