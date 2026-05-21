export interface PipelineState {
  step: number
  label: string
  timestamp: string
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
