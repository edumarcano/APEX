import { API_ENDPOINTS } from './api'

export type VoiceCueName =
  | 'activation_ready'
  | 'activation_loading'
  | 'activation_refresh_failed'
  | 'activation_no_fresh_telemetry'

export async function requestVoiceCue(
  cue: VoiceCueName,
): Promise<void> {
  try {
    await fetch(API_ENDPOINTS.voiceCue, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cue }),
    })
  } catch {
    // Contextual cues are best-effort; voice failures do not alter the operation.
  }
}
