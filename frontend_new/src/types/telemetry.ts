export interface TelemetryPayload {
  weather: string
  sports: string
  news: string
  email: string
  calendar: string
  reminders: string
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'
