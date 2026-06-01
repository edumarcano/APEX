export interface PipelineState {
  step: number
  label: string
  timestamp: string
  is_speaking: boolean
}

export interface SystemDiagnostics {
  cpu: number | null
  ram: number | null
  disk: number | null
}

export const DEFAULT_SYSTEM_DIAGNOSTICS: SystemDiagnostics = {
  cpu: null,
  ram: null,
  disk: null,
}

export interface ActiveReminder {
  id: number
  note: string
}

export interface TelemetryPayload {
  weather: string
  /** Integer °F for VTE primary readout; null when unavailable. */
  temperatureF: number | null
  /** Condition or summary text excluding the primary temperature numeral. */
  weatherDetail: string
  briefing: string
  sports: string
  news: string
  email: string
  calendar: string
  reminders: string
  activeReminders: ActiveReminder[]
  diagnostics?: SystemDiagnostics | null
}

export interface ApexDataState {
  data: TelemetryPayload | null
  status: 'idle' | 'loading' | 'success' | 'error'
  error: string | null
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
  isSpeaking: boolean
  activeReminders: ActiveReminder[]
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'

export type AtmosphericCondition = 'neutral' | 'stormy' | 'clear'

export interface AtmosphericTheme {
  condition: AtmosphericCondition
  isStormy: boolean
  bgColors: string
  textColor: string
  accentColor: string
}

export interface AtmosphericThemeContextType {
  theme: AtmosphericTheme
  updateThemeFromTelemetry: (weatherReport?: string) => void
}
