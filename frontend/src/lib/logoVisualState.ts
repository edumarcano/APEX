import type { SystemState } from '../types/telemetry'

export type OuterShellActivity =
  | 'normal'
  | 'collection'
  | 'synthesis'
  | 'local_loading'

export interface LogoVisualStateInput {
  briefingStatus: SystemState
  activeStep: number | null
  activated: boolean
  isBriefingRunning: boolean
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
  red: '220, 38, 38',
  rust: '249, 115, 22',
  slate: '15, 23, 42',
} as const

export function resolveOuterShellActivity({
  activeStep,
  isBriefingRunning,
  isLocalModelLoading,
  isTelemetryCollecting,
}: Pick<
  LogoVisualStateInput,
  'activeStep' | 'isBriefingRunning' | 'isLocalModelLoading' | 'isTelemetryCollecting'
>): OuterShellActivity {
  if (isLocalModelLoading) return 'local_loading'
  if (isBriefingRunning && activeStep === 3) return 'synthesis'
  if (
    isTelemetryCollecting ||
    (isBriefingRunning && (activeStep === 1 || activeStep === 2))
  ) {
    return 'collection'
  }
  return 'normal'
}

function resolveColor(input: LogoVisualStateInput): string {
  if (input.briefingStatus === 'error') return COLORS.red
  if (input.isLocalModelLoading) return COLORS.rust
  if (input.isCortexQuerying) return COLORS.purple
  if (input.activeStep === 4) return COLORS.gold
  if (input.briefingStatus === 'success' && !input.isSpeaking) {
    return input.isLocalModelLoaded ? COLORS.rust : COLORS.blue
  }
  if (input.activeStep === 3) return COLORS.purple
  if (
    input.isBriefingRunning ||
    input.isTelemetryCollecting ||
    input.activeStep === 1 ||
    input.activeStep === 2
  ) {
    return COLORS.green
  }
  if (input.isLocalModelLoaded) return COLORS.rust
  return input.activated ? COLORS.blue : COLORS.slate
}

export function resolveLogoVisualColors(input: LogoVisualStateInput): {
  atmosphere: string
  logo: string
} {
  return {
    atmosphere: resolveColor(input),
    logo: resolveColor(input),
  }
}
