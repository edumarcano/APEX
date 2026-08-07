import { describe, expect, it } from 'vitest'

import {
  buildSettingsTimingRuntime,
  cloneRuntimeSettings,
  diffSettingsPatch,
  filterAskApexSettingsForDevMode,
  isSettingsPatchEmpty,
  parseMcpStatusResponse,
  parseSettingsResponse,
  resolveAppliedAgentSelection,
  resolveAgentKey,
  resolveInitialAgentSelection,
  resolveEffectiveTiming,
  settingsAreEqual,
} from './settings'
import {
  BASE_SETTINGS,
  buildMcpStatusResponse,
  buildSettingsResponse,
} from '../test/settingsFixtures'

describe('assistant boot hydration', () => {
  it('does not reapply the saved selection after initial hydration', () => {
    const saved = { agent: 'panthera' as const, effort: 'focused' as const }

    expect(resolveInitialAgentSelection(false, saved, 'panthera')).toEqual(saved)
    expect(resolveInitialAgentSelection(true, saved, 'panthera')).toBeNull()
  })

  it('preserves a selected session profile after a DEV_MODE settings response', () => {
    const response = buildSettingsResponse()
    response.dev_mode_active = true

    expect(resolveAppliedAgentSelection(response, 'panthera', true)).toEqual({
      runtime: 'cloud',
      agent: 'panthera',
      effort: 'focused',
    })
    expect(resolveAppliedAgentSelection(response, 'acinonyx', false)).toEqual({
      runtime: 'cloud',
      agent: 'acinonyx',
      effort: 'focused',
    })
  })

  it('keeps effort, local reasoning, context, and native-tool preferences while filtering DEV_MODE profile fields', () => {
    expect(filterAskApexSettingsForDevMode({
      runtime: 'cloud',
      cloud_agent: 'neofelis',
      local_agent: 'mus',
      effort: 'extended',
      local_context_windows: { apodemus: 32768, neotoma: 16384 },
      local_reasoning_modes: { mus: 'none', apodemus: 'focused' },
      neofelis_google_search_enabled: false,
      neofelis_google_maps_enabled: true,
      delphinus_x_search_enabled: false,
      orcinus_x_search_enabled: true,
    })).toEqual({
      effort: 'extended',
      local_context_windows: { apodemus: 32768, neotoma: 16384 },
      local_reasoning_modes: { mus: 'none', apodemus: 'focused' },
      neofelis_google_search_enabled: false,
      neofelis_google_maps_enabled: true,
      delphinus_x_search_enabled: false,
      orcinus_x_search_enabled: true,
    })
  })
})

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
    ['assistant boolean', ['settings', 'ask_apex', 'enabled'], null],
    ['Agent runtime', ['settings', 'ask_apex', 'runtime'], 'invalid'],
    ['cloud profile', ['settings', 'ask_apex', 'cloud_agent'], 'invalid'],
    ['cloud effort', ['settings', 'ask_apex', 'effort'], 'invalid'],
    ['local profile', ['settings', 'ask_apex', 'local_agent'], 'invalid'],
    ['local context windows', ['settings', 'ask_apex', 'local_context_windows'], null],
    ['local reasoning modes', ['settings', 'ask_apex', 'local_reasoning_modes'], null],
    ['neofelis google search', ['settings', 'ask_apex', 'neofelis_google_search_enabled'], null],
    ['neofelis google maps', ['settings', 'ask_apex', 'neofelis_google_maps_enabled'], null],
    ['delphinus x search', ['settings', 'ask_apex', 'delphinus_x_search_enabled'], null],
    ['orcinus x search', ['settings', 'ask_apex', 'orcinus_x_search_enabled'], null],
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
    expect(clone.ask_apex).not.toBe(BASE_SETTINGS.ask_apex)
    expect(clone.ask_apex.local_context_windows).not.toBe(
      BASE_SETTINGS.ask_apex.local_context_windows,
    )
    expect(clone.ask_apex.local_reasoning_modes).not.toBe(
      BASE_SETTINGS.ask_apex.local_reasoning_modes,
    )
    expect(clone.briefing).not.toBe(BASE_SETTINGS.briefing)
    expect(clone.voice).not.toBe(BASE_SETTINGS.voice)
    expect(clone.mcp).not.toBe(BASE_SETTINGS.mcp)
    expect(clone.mcp.servers.github).not.toBe(BASE_SETTINGS.mcp.servers.github)
  })

  it('resolves the active Agent from mode', () => {
    expect(resolveAgentKey(BASE_SETTINGS.ask_apex)).toBe('panthera')
    expect(
      resolveAgentKey({
        ...BASE_SETTINGS.ask_apex,
        runtime: 'local',
        local_agent: 'sorex',
      }),
    ).toBe('sorex')
  })

  it('includes football teams and market symbols in settings patches', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.football.teams = [{ id: 81, name: 'Barcelona' }]
    draft.market.symbols = ['SPY', 'AAPL']

    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      football: { teams: [{ id: 81, name: 'Barcelona' }] },
      market: { symbols: ['SPY', 'AAPL'] },
    })
  })

  it('generates a patch containing only dirty fields', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.user_designation = 'Chief'
    draft.features.weather = false
    draft.features.market = false
    draft.ask_apex.runtime = 'local'
    draft.ask_apex.local_agent = 'sorex'
    draft.ask_apex.local_context_windows = {
      ...draft.ask_apex.local_context_windows,
      apodemus: 16384,
    }
    draft.briefing.default_mode = 'mus'
    draft.voice.gender = 'male'
    draft.voice.mode = 'manual'
    draft.mcp.enabled = true
    draft.mcp.servers.github.enabled = true

    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      user_designation: 'Chief',
      features: { weather: false, market: false },
      ask_apex: {
        runtime: 'local',
        local_agent: 'sorex',
        local_context_windows: { apodemus: 16384, neotoma: 16384 },
      },
      briefing: { default_mode: 'mus' },
      voice: { gender: 'male', mode: 'manual' },
      mcp: {
        enabled: true,
        servers: { github: { enabled: true } },
      },
    })
  })

  it('includes llama_cpp changes in settings patches', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.llama_cpp.enabled = true
    draft.llama_cpp.managed = true
    draft.llama_cpp.host = 'http://localhost:8181'
    draft.llama_cpp.executable_path = 'C:\\Tools\\llama-server.exe'
    draft.llama_cpp.preset_path = 'C:\\Tools\\preset.ini'
    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      llama_cpp: {
        enabled: true,
        managed: true,
        host: 'http://localhost:8181',
        executable_path: 'C:\\Tools\\llama-server.exe',
        preset_path: 'C:\\Tools\\preset.ini',
      },
    })
    expect(isSettingsPatchEmpty(diffSettingsPatch(BASE_SETTINGS, draft))).toBe(false)
  })

  it('persists independent local contexts through ask_apex patch', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.ask_apex.local_context_windows = {
      ...draft.ask_apex.local_context_windows,
      neotoma: 65536,
    }
    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      ask_apex: {
        local_context_windows: { apodemus: 8192, neotoma: 65536 },
      },
    })
  })

  it('persists local reasoning modes through ask_apex patch', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.ask_apex.local_reasoning_modes = {
      ...draft.ask_apex.local_reasoning_modes,
      apodemus: 'focused',
    }
    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      ask_apex: {
        local_reasoning_modes: {
          sorex: 'none',
          mus: 'none',
          apodemus: 'focused',
          neotoma: 'none',
        },
      },
    })
  })

  it('keeps local context patches isolated from llama_cpp settings', () => {
    const draft = cloneRuntimeSettings(BASE_SETTINGS)
    draft.ask_apex.local_context_windows = {
      ...draft.ask_apex.local_context_windows,
      apodemus: 32768,
    }
    draft.llama_cpp.enabled = true
    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      ask_apex: {
        local_context_windows: { apodemus: 32768, neotoma: 16384 },
      },
      llama_cpp: { enabled: true },
    })
  })

  it('accepts apodemus as a local Agent key', () => {
    expect(
      resolveAgentKey({
        ...BASE_SETTINGS.ask_apex,
        runtime: 'local',
        local_agent: 'apodemus',
      }),
    ).toBe('apodemus')
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
      isCortexQuerying: false,
    })

    expect(resolveEffectiveTiming('features', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('modules', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('ask_apex', runtime)).toBe('Active')
    expect(resolveEffectiveTiming('voice', runtime)).toBe('Active')
  })

  it('reports the next briefing for captured connector settings', () => {
    const runtime = buildSettingsTimingRuntime({
      status: 'loading',
      pipelineStep: 2,
      isSpeaking: false,
      isCortexQuerying: false,
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
      isCortexQuerying: true,
    })

    expect(resolveEffectiveTiming('ask_apex', runtime)).toBe(
      'Applies next response',
    )
  })

  it('reports this delivery before speech and the next delivery during speech', () => {
    const collecting = buildSettingsTimingRuntime({
      status: 'loading',
      pipelineStep: 3,
      isSpeaking: false,
      isCortexQuerying: false,
    })
    const speaking = buildSettingsTimingRuntime({
      status: 'success',
      pipelineStep: 4,
      isSpeaking: true,
      isCortexQuerying: false,
    })

    expect(resolveEffectiveTiming('voice', collecting)).toBe(
      'Applies this delivery',
    )
    expect(resolveEffectiveTiming('voice', speaking)).toBe(
      'Applies next delivery',
    )
  })
})
