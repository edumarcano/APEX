import { API_ENDPOINTS } from './api'
import type { BriefingMode } from '../types/settings'

export type VoiceCueName =
  | 'activation_ready'
  | 'activation_loading'
  | 'activation_refresh_failed'
  | 'activation_no_fresh_telemetry'
  | 'start_with_briefing'
  | 'briefing_refresh'
  | 'briefing_existing_snapshot'
  | 'briefing_collection_complete'
  | 'briefing_partial_sources'
  | 'briefing_sources_unavailable'
  | 'briefing_no_snapshot'
  | 'briefing_generation_failed'

export async function requestVoiceCue(
  cue: VoiceCueName,
  mode?: BriefingMode,
): Promise<void> {
  try {
    await fetch(API_ENDPOINTS.voiceCue, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cue, ...(mode ? { mode } : {}) }),
    })
  } catch {
    // Contextual cues are best-effort; voice failures do not alter the operation.
  }
}
