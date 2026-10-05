import type {
  McpStatusResponse,
  RuntimeSettings,
  SettingsResponse,
} from '../types/settings'

export const BASE_SETTINGS: RuntimeSettings = {
  user_designation: '',
  agent_display_name: '',
  features: {
    weather: true,
    sports: true,
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
  calendar: {
    selected_calendar_ids: ['primary'],
    show_calendar_names: true,
  },
  context_vault: {
    enabled: false,
    scopes: [],
  },
  ask_apex: {
    enabled: true,
    selected_model: 'z-ai/glm-5.3-flash',
    sandbox_mode: false,
    cloud: {
      last_model: 'z-ai/glm-5.3-flash',
      effort: 'low',
      personal_context_enabled: false,
      hosted_tools: { google_search: true, google_maps: true },
    },
    local: {
      last_model: 'gemma-4-E2B-Q4_K_M.gguf',
      context_window: 16384,
      reasoning_mode: 'none',
      personal_context_enabled: false,
    },
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
  activity_report_folder: {
    enabled: false,
    folder_path: '',
  },
  desktop: {
    launch_on_startup: false,
    completion_notifications: false,
  },
  device_context: { location_enabled: false },
}

export function buildSettingsResponse(
  settings: RuntimeSettings = BASE_SETTINGS,
  overrides: Partial<SettingsResponse> = {},
): SettingsResponse {
  return {
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
