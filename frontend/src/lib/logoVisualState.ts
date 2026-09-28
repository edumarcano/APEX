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
  const activeColor = activityColor(input.activity)
  const atmosphere = input.isLocalModelLoading
    ? COLORS.rust
    : input.activity !== 'briefing_ready' && activeColor !== null
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
    logo: input.isLocalModelLoading
      ? COLORS.rust
      : input.isLocalModelLoaded
        ? COLORS.rust
        : atmosphere,
  }
}
