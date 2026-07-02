export type TtsEngine = 'google' | 'kokoro' | 'pyttsx3'

export interface PipelineState {
  step: number
  label: string
  timestamp: string
  is_speaking: boolean
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
}

export interface SystemDiagnostics {
  cpu: number | null
  cpu_freq: number | null
  ram: number | null
  ram_used: number | null
  ram_total: number | null
  disk: number | null
  disk_used: number | null
  disk_total: number | null
}

export const DEFAULT_SYSTEM_DIAGNOSTICS: SystemDiagnostics = {
  cpu: null,
  cpu_freq: null,
  ram: null,
  ram_used: null,
  ram_total: null,
  disk: null,
  disk_used: null,
  disk_total: null,
}

export interface ActiveReminder {
  id: number
  note: string
}

export type WeatherConditionArchetype =
  | 'clear_day'
  | 'clear_night'
  | 'clouds'
  | 'rain'
  | 'thunderstorm'

export type AgentCloudProfile = 'comet' | 'nova' | 'pulsar'

export interface DigestPayload {
  insights: string[]
}

export interface TelemetryPayload {
  weather: string
  /** Integer °F for VTE primary readout; null when unavailable. */
  temperatureF: number | null
  /** Condition or summary text excluding the primary temperature numeral. */
  weatherDetail: string
  /** Parsed micro-climate archetype for scoped card glow and border theming. */
  weatherCondition?: WeatherConditionArchetype | null
  briefing: string
  sports: string
  news: string
  email: string
  calendar: string
  reminders: string
  activeReminders: ActiveReminder[]
  diagnostics?: SystemDiagnostics | null
  confidenceScore: number
  failedConnectors: string[]
  digest?: DigestPayload
  defaultProfile?: AgentCloudProfile
  askApexEnabled?: boolean
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'

export interface ApexDataState {
  data: TelemetryPayload | null
  status: SystemState
  error: string | null
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
  isSpeaking: boolean
  activeReminders: ActiveReminder[]
  demoModeActive: boolean
  confidenceScore: number
  failedConnectors: string[]
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
  defaultProfile?: AgentCloudProfile
  askApexEnabled?: boolean
}
