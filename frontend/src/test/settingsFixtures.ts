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
    agent: 'panthera',
    sandbox_mode: false,
    panthera: {
      model: 'gpt-5.6-luna',
      effort: 'medium',
      hosted_tools: {
        google_search: true,
        google_maps: true,
        x_search: true,
      },
    },
    felis: {
      model: 'gemma-4-E2B-Q4_K_M.gguf',
      context_window: 16384,
      reasoning_mode: 'none',
    },
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
  microsoft_todo: {
    reminder_list_id: '',
  },
}

export function buildSettingsResponse(
  settings: RuntimeSettings = BASE_SETTINGS,
  overrides: Partial<SettingsResponse> = {},
): SettingsResponse {
  return {
    schema_version: 16,
    settings,
    local_file_present: false,
    local_override_active: false,
    load_warning: null,
    dev_mode_active: false,
    demo_mode_active: false,
    ...overrides,
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
