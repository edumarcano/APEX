import type {
  McpStatusResponse,
  RuntimeSettings,
  SettingsResponse,
} from '../types/settings'

export const BASE_SETTINGS: RuntimeSettings = {
  features: {
    weather: true,
    sports: true,
    news: true,
    email: false,
    calendar: false,
    market: true,
  },
  modules: {
    football: false,
    f1: true,
  },
  assistant: {
    enabled: true,
    mode: 'cloud',
    cloud_profile: 'panthera',
    cloud_effort: 'focused',
    local_profile: 'mus',
    neofelis_google_search_enabled: true,
  },
  briefing: {
    default_mode: 'panthera',
  },
  voice: {
    engine: 'google',
    gender: 'female',
    mode: 'automatic',
  },
  mcp: {
    enabled: false,
    servers: {
      github: { enabled: false },
      brave: { enabled: false },
      alphavantage: { enabled: false },
    },
  },
}

export function buildSettingsResponse(
  settings: RuntimeSettings = BASE_SETTINGS,
): SettingsResponse {
  return {
    schema_version: 6,
    settings,
    local_file_present: false,
    local_override_active: false,
    load_warning: null,
    dev_mode_active: false,
    demo_mode_active: false,
  }
}

export function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

export function buildMcpStatusResponse(
  overrides: Partial<McpStatusResponse> = {},
): McpStatusResponse {
  return {
    enabled: false,
    status: 'disabled',
    reason: 'MCP client runtime is disabled.',
    servers: [],
    ...overrides,
  }
}
