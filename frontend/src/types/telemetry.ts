export interface PipelineState {
  step: number
  label: string
  timestamp: string
}

export interface TelemetryPayload {
  weather: string
  briefing: string
  sports: string
  news: string
  email: string
  calendar: string
  reminders: string
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'
