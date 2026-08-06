import type {
  McpStatusResponse,
  RuntimeSettings,
  SettingsResponse,
} from '../types/settings'

export const BASE_SETTINGS: RuntimeSettings = {
  user_designation: '',
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
  football: {
    teams: [],
  },
  market: {
    symbols: [],
  },
  ask_apex: {
    enabled: true,
    runtime: 'cloud',
    cloud_agent: 'panthera',
    effort: 'focused',
    local_agent: 'mus',
    apodemus_context_window: 8192,
    neofelis_google_search_enabled: true,
    neofelis_google_maps_enabled: true,
    delphinus_x_search_enabled: true,
    orcinus_x_search_enabled: true,
    tool_routing_mode: 'shadow',
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
  llama_cpp: {
    enabled: false,
    managed: false,
    host: 'http://127.0.0.1:8080',
    executable_path: '',
    preset_path: '',
  },
}

export function buildSettingsResponse(
  settings: RuntimeSettings = BASE_SETTINGS,
): SettingsResponse {
  return {
    schema_version: 11,
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
