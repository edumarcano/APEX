export interface PipelineState {
  step: number
  label: string
  timestamp: string
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
  diagnostics?: SystemDiagnostics | null
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
