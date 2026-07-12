import type { RuntimeSettings, SettingsResponse } from '../types/settings'

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
    default_profile: 'comet',
  },
  voice: {
    engine: 'google',
    gender: 'female',
  },
}

export function buildSettingsResponse(
  settings: RuntimeSettings = BASE_SETTINGS,
): SettingsResponse {
  return {
    schema_version: 2,
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
