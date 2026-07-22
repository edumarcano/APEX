export const API_BASE = 'http://127.0.0.1:8000'

export const API_ENDPOINTS = {
  agentLocalUnload: `${API_BASE}/api/v1/local-model/unload`,
  agentProfiles: `${API_BASE}/api/v1/agent/profiles`,
  agentQuery: `${API_BASE}/api/v1/agent/query`,
  briefingHistory: `${API_BASE}/api/v1/briefings/history`,
  config: `${API_BASE}/api/v1/config`,
  diagnostics: `${API_BASE}/api/v1/diagnostics`,
  market: `${API_BASE}/api/v1/market`,
  preflight: `${API_BASE}/api/v1/preflight`,
  reminders: `${API_BASE}/api/v1/reminders`,
  remindersRead: `${API_BASE}/api/v1/reminders/read`,
  settings: `${API_BASE}/api/v1/settings`,
  status: `${API_BASE}/api/v1/status`,
  telemetryLatest: `${API_BASE}/api/v1/telemetry/latest`,
  telemetryRefresh: `${API_BASE}/api/v1/telemetry/refresh`,
  trigger: `${API_BASE}/api/v1/trigger`,
} as const
