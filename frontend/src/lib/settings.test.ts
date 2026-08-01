import { describe, expect, it } from 'vitest'

import {
  buildSettingsTimingRuntime,
  cloneRuntimeSettings,
  diffSettingsPatch,
  isSettingsPatchEmpty,
  parseMcpStatusResponse,
  parseSettingsResponse,
  resolveAssistantProfile,
  resolveEffectiveTiming,
  settingsAreEqual,
} from './settings'
import {
  BASE_SETTINGS,
  buildMcpStatusResponse,
  buildSettingsResponse,
} from '../test/settingsFixtures'

describe('settings response parsing', () => {
  it('accepts a complete valid response', () => {
    expect(parseSettingsResponse(buildSettingsResponse())).toEqual(
      buildSettingsResponse(),
    )
  })

  it.each([
    ['feature boolean', ['settings', 'features', 'weather'], 'yes'],
    ['market boolean', ['settings', 'features', 'market'], 'yes'],
    ['module boolean', ['settings', 'modules', 'f1'], 1],
    ['assistant boolean', ['settings', 'assistant', 'enabled'], null],
    ['assistant mode', ['settings', 'assistant', 'mode'], 'invalid'],
    ['cloud profile', ['settings', 'assistant', 'cloud_profile'], 'invalid'],
    ['cloud effort', ['settings', 'assistant', 'cloud_effort'], 'invalid'],
    ['local profile', ['settings', 'assistant', 'local_profile'], 'invalid'],
    ['neofelis google search', ['settings', 'assistant', 'neofelis_google_search_enabled'], null],
    ['briefing mode', ['settings', 'briefing', 'default_mode'], 'invalid'],
    ['voice engine', ['settings', 'voice', 'engine'], 'invalid'],
    ['voice gender', ['settings', 'voice', 'gender'], 'invalid'],
    ['voice mode', ['settings', 'voice', 'mode'], 'invalid'],
    ['MCP master boolean', ['settings', 'mcp', 'enabled'], 'yes'],
    ['MCP provider boolean', ['settings', 'mcp', 'servers', 'github', 'enabled'], 1],
    ['schema version', ['schema_version'], '1'],
    ['local file flag', ['local_file_present'], 'false'],
    ['local override flag', ['local_override_active'], 0],
    ['load warning', ['load_warning'], 42],
    ['development mode flag', ['dev_mode_active'], 'false'],
    ['demo mode flag', ['demo_mode_active'], undefined],
  ])('rejects a malformed %s', (_label, path, replacement) => {
    const body = structuredClone(buildSettingsResponse()) as unknown as Record<
      string,
      unknown
    >
    let target = body
    for (const segment of path.slice(0, -1)) {
      target = target[segment] as Record<string, unknown>
    }
    target[path[path.length - 1]] = replacement

    expect(parseSettingsResponse(body)).toBeNull()
  })

  it('rejects missing settings sections', () => {
    const body = structuredClone(buildSettingsResponse()) as unknown as Record<
      string,
      unknown
    >
    delete (body.settings as Record<string, unknown>).voice

    expect(parseSettingsResponse(body)).toBeNull()
  })
})

describe('settings editing utilities', () => {
  it('clones every nested settings section', () => {
    const clone = cloneRuntimeSettings(BASE_SETTINGS)

    expect(clone).toEqual(BASE_SETTINGS)
    expect(clone).not.toBe(BASE_SETTINGS)
    expect(clone.features).not.toBe(BASE_SETTINGS.features)
    expect(clone.modules).not.toBe(BASE_SETTINGS.modules)
    expect(clone.assistant).not.toBe(BASE_SETTINGS.assistant)
    expect(clone.briefing).not.toBe(BASE_SETTINGS.briefing)
    expect(clone.voice).not.toBe(BASE_SETTINGS.voice)
    expect(clone.mcp).not.toBe(BASE_SETTINGS.mcp)
    expect(clone.mcp.servers.github).not.toBe(BASE_SETTINGS.mcp.servers.github)
  })

  it('resolves the active assistant profile from mode', () => {
    expect(resolveAssistantProfile(BASE_SETTINGS.assistant)).toBe('panthera')
    expect(
      resolveAssistantProfile({
        ...BASE_SETTINGS.assistant,
        mode: 'local',
        local_profile: 'sorex',
      }),
    ).toBe('sorex')
  })

  it('generates a patch containing only dirty fields', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.features.weather = false
    draft.features.market = false
    draft.assistant.mode = 'local'
    draft.assistant.local_profile = 'sorex'
    draft.briefing.default_mode = 'mus'
    draft.voice.gender = 'male'
    draft.voice.mode = 'manual'
    draft.mcp.enabled = true
    draft.mcp.servers.github.enabled = true

    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      features: { weather: false, market: false },
      assistant: { mode: 'local', local_profile: 'sorex' },
      briefing: { default_mode: 'mus' },
      voice: { gender: 'male', mode: 'manual' },
      mcp: {
        enabled: true,
        servers: { github: { enabled: true } },
      },
    })
  })

  it('recognizes empty patches and equal settings', () => {
    const clone = cloneRuntimeSettings(BASE_SETTINGS)

    expect(diffSettingsPatch(BASE_SETTINGS, clone)).toEqual({})
    expect(isSettingsPatchEmpty({})).toBe(true)
    expect(settingsAreEqual(BASE_SETTINGS, clone)).toBe(true)

    clone.modules.football = true
    expect(settingsAreEqual(BASE_SETTINGS, clone)).toBe(false)
  })
})

describe('MCP status parsing', () => {
  it('accepts sanitized provider status', () => {
    const body = buildMcpStatusResponse({
      enabled: true,
      status: 'connected',
      servers: [
        {
          id: 'github',
          enabled: true,
          transport: 'http',
          status: 'connected',
          reason: 'Connected.',
          registered_tools: ['github_search_code'],
        },
      ],
    })
    expect(parseMcpStatusResponse(body)).toEqual(body)
  })

  it('rejects malformed tool lists and statuses', () => {
    const malformed = buildMcpStatusResponse() as unknown as Record<string, unknown>
    malformed.status = 'secret-provider-state'
    expect(parseMcpStatusResponse(malformed)).toBeNull()
  })
})

describe('effective timing', () => {
  it('reports active settings when no operation owns a snapshot', () => {
    const runtime = buildSettingsTimingRuntime({
      status: 'idle',
      pipelineStep: null,
      isSpeaking: false,
      isAssistantQuerying: false,
    })

    expect(resolveEffectiveTiming('features', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('modules', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('assistant', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('voice', runtime)).toBe('Active')
  })

  it('reports the next briefing for captured connector settings', () => {
    const runtime = buildSettingsTimingRuntime({
      status: 'loading',
      pipelineStep: 2,
      isSpeaking: false,
      isAssistantQuerying: false,
    })

    expect(resolveEffectiveTiming('features', runtime)).toBe(
      'Applies next briefing',
    )
    expect(resolveEffectiveTiming('market', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('modules', runtime)).toBe(
      'Applies next briefing',
    )
  })

  it('reports the next response while the assistant is querying', () => {
    const runtime = buildSettingsTimingRuntime({
      status: 'success',
      pipelineStep: null,
      isSpeaking: false,
      isAssistantQuerying: true,
    })

    expect(resolveEffectiveTiming('assistant', runtime)).toBe(
      'Applies next response',
    )
  })

  it('reports this delivery before speech and the next delivery during speech', () => {
    const collecting = buildSettingsTimingRuntime({
      status: 'loading',
      pipelineStep: 3,
      isSpeaking: false,
      isAssistantQuerying: false,
    })
    const speaking = buildSettingsTimingRuntime({
      status: 'success',
      pipelineStep: 4,
      isSpeaking: true,
      isAssistantQuerying: false,
    })

    expect(resolveEffectiveTiming('voice', collecting)).toBe(
      'Applies this delivery',
    )
    expect(resolveEffectiveTiming('voice', speaking)).toBe(
      'Applies next delivery',
    )
  })
})
