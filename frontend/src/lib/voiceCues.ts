import { API_ENDPOINTS } from './api'
import type { BriefingProfileId } from '../types/briefings'

export type VoiceCueName =
  | 'activation_ready'
  | 'activation_loading'
  | 'activation_refresh_failed'
  | 'activation_no_fresh_telemetry'
  | 'briefing_generating'
  | 'briefing_ready'
  | 'briefing_failed'
  | 'highlights_ready'
  | 'highlights_failed'

export type VoiceCueOptions = {
  briefingProfile?: BriefingProfileId
}

export async function requestVoiceCue(
  cue: VoiceCueName,
  options: VoiceCueOptions = {},
): Promise<void> {
  try {
    await fetch(API_ENDPOINTS.voiceCue, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cue,
        ...(options.briefingProfile ? { briefing_profile: options.briefingProfile } : {}),
      }),
    })
  } catch {
    // Contextual cues are best-effort; voice failures do not alter the operation.
  }
}

/**
 * Reports whether a normal refresh will collect new telemetry. Any failure to
 * confirm this returns false so an unverified "collecting" cue is not spoken.
 */
export async function willCollectFreshTelemetry(): Promise<boolean> {
  try {
    const response = await fetch(API_ENDPOINTS.telemetryReuse)
    if (!response.ok) return false
    const body: unknown = await response.json()
    return typeof body === 'object' && body !== null && (body as { reusable?: unknown }).reusable === false
  } catch {
    return false
  }
}
