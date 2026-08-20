import { describe, expect, it } from 'vitest'

import {
  buildSettingsTimingRuntime,
  cloneRuntimeSettings,
  defaultSandboxMode,
  diffSettingsPatch,
  filterAgentSettingsForDevMode,
  isSettingsPatchEmpty,
  parseMcpStatusResponse,
  parseSettingsResponse,
  resolveAppliedAgentSelection,
  resolveAgentKey,
  resolveHistoryPartition,
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
    const saved = { agent: 'panthera' as const, effort: 'medium' as const }

    expect(resolveInitialAgentSelection(false, saved, 'panthera')).toEqual(saved)
    expect(resolveInitialAgentSelection(true, saved, 'panthera')).toBeNull()
  })

  it('preserves a selected session agent after a DEV_MODE settings response', () => {
    const response = buildSettingsResponse()
    response.dev_mode_active = true
    response.settings.ask_apex.sandbox_mode = true

    expect(resolveAppliedAgentSelection(response, 'panthera', true)).toEqual({
      runtime: 'cloud',
      agent: 'panthera',
      effort: 'medium',
      sandboxMode: true,
    })
    expect(resolveAppliedAgentSelection(response, 'felis', true)).toEqual({
      runtime: 'local',
      agent: 'felis',
      effort: null,
      sandboxMode: true,
    })
  })

  it('defaults sandbox mode on during initial DEV_MODE hydration', () => {
    const response = buildSettingsResponse(undefined, { dev_mode_active: true })
    response.settings.ask_apex.sandbox_mode = false

    expect(resolveAppliedAgentSelection(response, 'panthera', false)).toEqual({
      runtime: 'cloud',
      agent: 'panthera',
      effort: 'medium',
      sandboxMode: false,
    })
    expect(defaultSandboxMode(undefined)).toBe(true)
  })

  it('keeps nested Panthera and Felis preferences while filtering DEV_MODE identity fields', () => {
    expect(filterAgentSettingsForDevMode({
      agent: 'felis',
      sandbox_mode: true,
      panthera: { effort: 'high', hosted_tools: { google_search: false } },
      felis: { context_window: 32768, reasoning_mode: 'focused' },
    })).toEqual({
      sandbox_mode: true,
      panthera: { effort: 'high', hosted_tools: { google_search: false } },
      felis: { context_window: 32768, reasoning_mode: 'focused' },
    })
  })

  it('resolves history partitions from sandbox mode', () => {
    expect(resolveHistoryPartition(false, true)).toBe('production')
    expect(resolveHistoryPartition(true, false)).toBe('production')
    expect(resolveHistoryPartition(true, true)).toBe('sandbox')
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
    ['Agent queries enabled', ['settings', 'ask_apex', 'enabled'], null],
    ['Agent key', ['settings', 'ask_apex', 'agent'], 'invalid'],
    ['sandbox mode', ['settings', 'ask_apex', 'sandbox_mode'], 'yes'],
    ['panthera model', ['settings', 'ask_apex', 'panthera', 'model'], ''],
    ['panthera effort', ['settings', 'ask_apex', 'panthera', 'effort'], 'invalid'],
    ['felis model', ['settings', 'ask_apex', 'felis', 'model'], ''],
    ['felis context window', ['settings', 'ask_apex', 'felis', 'context_window'], 0],
    ['felis reasoning mode', ['settings', 'ask_apex', 'felis', 'reasoning_mode'], 'invalid'],
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

describe('settings cloning and mutations', () => {
  it('deep clones settings values to isolate draft mutations', () => {
    const clone = cloneRuntimeSettings(BASE_SETTINGS)

    expect(clone).toEqual(BASE_SETTINGS)
    expect(clone).not.toBe(BASE_SETTINGS)
    expect(clone.features).not.toBe(BASE_SETTINGS.features)
    expect(clone.modules).not.toBe(BASE_SETTINGS.modules)
    expect(clone.ask_apex).not.toBe(BASE_SETTINGS.ask_apex)
    expect(clone.ask_apex.panthera).not.toBe(BASE_SETTINGS.ask_apex.panthera)
    expect(clone.ask_apex.felis).not.toBe(BASE_SETTINGS.ask_apex.felis)
    expect(clone.briefing).not.toBe(BASE_SETTINGS.briefing)
    expect(clone.voice).not.toBe(BASE_SETTINGS.voice)
    expect(clone.mcp).not.toBe(BASE_SETTINGS.mcp)
    expect(clone.mcp.servers.github).not.toBe(BASE_SETTINGS.mcp.servers.github)
  })

  it('resolves the active Agent from settings', () => {
    expect(resolveAgentKey(BASE_SETTINGS.ask_apex)).toBe('panthera')
    expect(
      resolveAgentKey({
        ...BASE_SETTINGS.ask_apex,
        agent: 'felis',
      }),
    ).toBe('felis')
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
    draft.ask_apex.agent = 'felis'
    draft.ask_apex.felis.context_window = 32768
    draft.briefing.default_mode = 'flash'
    draft.voice.gender = 'male'
    draft.voice.mode = 'manual'
    draft.mcp.enabled = true
    draft.mcp.servers.github.enabled = true

    expect(diffSettingsPatch(BASE_SETTINGS, draft)).toEqual({
      user_designation: 'Chief',
      features: { weather: false, market: false },
      ask_apex: {
        agent: 'felis',
        felis: {
          ...BASE_SETTINGS.ask_apex.felis,
          context_window: 32768,
        },
      },
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

  it('reports no patch when settings are equal', () => {
    expect(settingsAreEqual(BASE_SETTINGS, cloneRuntimeSettings(BASE_SETTINGS))).toBe(true)
    expect(isSettingsPatchEmpty(diffSettingsPatch(BASE_SETTINGS, BASE_SETTINGS))).toBe(true)
  })

  it('parses MCP status responses', () => {
    expect(parseMcpStatusResponse(buildMcpStatusResponse())).toEqual(buildMcpStatusResponse())
  })

  it('resolves effective timing for settings groups', () => {
    const runtime = buildSettingsTimingRuntime({
      status: 'loading',
      pipelineStep: 2,
      isSpeaking: false,
      isCortexQuerying: false,
    })
    expect(resolveEffectiveTiming('features', runtime)).toBe('Applies next briefing')
    expect(resolveEffectiveTiming('agent_queries', {
      ...runtime,
      isCortexQuerying: true,
    })).toBe('Applies next response')
  })
})
