import { isLocalAgentKey, runtimeForAgentKey } from './agents'
import type {
  AgentRuntime,
  AgentKey,
  AgentInitialSelection,
  CloudEffort,
  CloudSettingsAgent,
  LocalSettingsAgent,
  SystemState,
  TtsEngine,
} from '../types/telemetry'
import type {
  BriefingMode,
  FeaturesSettings,
  FootballSettings,
  MarketSettings,
  ModulesSettings,
  McpSettings,
  McpStatusResponse,
  RuntimeSettings,
  SettingsEffectiveTiming,
  SettingsPatch,
  SettingsResponse,
  SettingsTimingFieldGroup,
  SettingsTimingRuntime,
  ToolProfilesSettings,
  ToolProfileSettings,
  LlamaCppServerStatusResponse,
  LocalContextWindows,
  VoiceGender,
  VoiceMode,
} from '../types/settings'
import { MCP_PROVIDER_IDS } from './mcpProviders'

const VALID_CLOUD_SETTINGS_AGENTS: readonly CloudSettingsAgent[] = [
  'panthera',
  'neofelis',
  'delphinus',
  'orcinus',
]

const VALID_LOCAL_SETTINGS_AGENTS: readonly LocalSettingsAgent[] = [
  'sorex',
  'mus',
  'apodemus',
  'neotoma',
]

export { isLocalAgentKey } from './agents'

export function resolveInitialAgentSelection(
  alreadyHydrated: boolean,
  selection: { agent: AgentKey; effort: CloudEffort | null } | undefined,
  defaultAgent: AgentKey | undefined,
): { agent: AgentKey; effort: CloudEffort | null } | null {
  if (alreadyHydrated) return null
  if (selection) return selection
  if (defaultAgent) return { agent: defaultAgent, effort: null }
  return null
}

/**
 * Resolve an Agent selection from a settings response without allowing
 * the DEV_MODE startup override to clobber an already-selected session
 * agent. DEV_MODE defaults to Acinonyx only during initial hydration;
 * subsequent settings responses preserve the active Cortex selection.
 */
export function resolveAppliedAgentSelection(
  response: SettingsResponse,
  currentAgent: AgentKey,
  selectionHydrated: boolean,
): AgentInitialSelection {
  if (response.dev_mode_active && !selectionHydrated) {
    return {
      runtime: 'cloud',
      agent: 'acinonyx',
      effort: response.settings.ask_apex.effort,
    }
  }

  if (response.dev_mode_active) {
    return {
      runtime: runtimeForAgentKey(currentAgent),
      agent: currentAgent,
      effort: isLocalAgentKey(currentAgent)
        ? null
        : response.settings.ask_apex.effort,
    }
  }

  return {
    runtime: response.settings.ask_apex.runtime,
    agent: resolveAgentKey(response.settings.ask_apex),
    effort:
      response.settings.ask_apex.runtime === 'cloud'
        ? response.settings.ask_apex.effort
        : null,
  }
}

const DEV_MODE_AGENT_SETTINGS_KEYS = new Set([
  'effort',
  'local_context_windows',
  'neofelis_google_search_enabled',
  'neofelis_google_maps_enabled',
  'delphinus_x_search_enabled',
  'orcinus_x_search_enabled',
])

/**
 * Keep session-only agent selection out of persisted DEV_MODE settings,
 * while allowing effort and grounding preferences to remain configurable.
 */
export function filterAskApexSettingsForDevMode(
  ask_apex: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(ask_apex).filter(([key]) => DEV_MODE_AGENT_SETTINGS_KEYS.has(key)),
  )
}

const VALID_ASSISTANT_MODES: readonly AgentRuntime[] = ['cloud', 'local']

const VALID_CLOUD_EFFORTS: readonly CloudEffort[] = ['light', 'focused', 'extended']

const VALID_BRIEFING_MODES: readonly BriefingMode[] = [
  'panthera',
  'mus',
  'sorex',
  'structured_digest',
]

const VALID_TTS_ENGINES: readonly TtsEngine[] = ['google', 'kokoro', 'pyttsx3']
const VALID_VOICE_GENDERS: readonly VoiceGender[] = ['male', 'female']
const VALID_VOICE_MODES: readonly VoiceMode[] = ['off', 'manual', 'automatic']
const VALID_MCP_STATUSES = [
  'configured',
  'connected',
  'degraded',
  'disabled',
  'authentication-required',
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isCloudSettingsAgent(value: unknown): value is CloudSettingsAgent {
  return (
    typeof value === 'string' &&
    (VALID_CLOUD_SETTINGS_AGENTS as readonly string[]).includes(value)
  )
}

function isLocalSettingsAgent(value: unknown): value is LocalSettingsAgent {
  return (
    typeof value === 'string' &&
    (VALID_LOCAL_SETTINGS_AGENTS as readonly string[]).includes(value)
  )
}

function parseLocalContextWindows(value: unknown): LocalContextWindows | null {
  if (!isRecord(value)) {
    return null
  }
  const entries = Object.entries(value)
  if (
    !entries.every(
      ([agent, contextWindow]) =>
        agent.trim().length > 0 &&
        typeof contextWindow === 'number' &&
        Number.isInteger(contextWindow) &&
        contextWindow > 0,
    )
  ) {
    return null
  }
  return Object.fromEntries(entries) as LocalContextWindows
}

function isAgentRuntime(value: unknown): value is AgentRuntime {
  return (
    typeof value === 'string' && (VALID_ASSISTANT_MODES as readonly string[]).includes(value)
  )
}

function isCloudEffort(value: unknown): value is CloudEffort {
  return (
    typeof value === 'string' && (VALID_CLOUD_EFFORTS as readonly string[]).includes(value)
  )
}

function isBriefingMode(value: unknown): value is BriefingMode {
  return (
    typeof value === 'string' &&
    (VALID_BRIEFING_MODES as readonly string[]).includes(value)
  )
}

function isTtsEngine(value: unknown): value is TtsEngine {
  return typeof value === 'string' && (VALID_TTS_ENGINES as readonly string[]).includes(value)
}

function isVoiceGender(value: unknown): value is VoiceGender {
  return (
    typeof value === 'string' && (VALID_VOICE_GENDERS as readonly string[]).includes(value)
  )
}

function isVoiceMode(value: unknown): value is VoiceMode {
  return (
    typeof value === 'string' && (VALID_VOICE_MODES as readonly string[]).includes(value)
  )
}

function parseFeatures(value: unknown): FeaturesSettings | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value.weather !== 'boolean' ||
    typeof value.sports !== 'boolean' ||
    typeof value.news !== 'boolean' ||
    typeof value.email !== 'boolean' ||
    typeof value.calendar !== 'boolean' ||
    typeof value.market !== 'boolean'
  ) {
    return null
  }
  return {
    weather: value.weather,
    sports: value.sports,
    news: value.news,
    email: value.email,
    calendar: value.calendar,
    market: value.market,
  }
}

function parseModules(value: unknown): ModulesSettings | null {
  if (!isRecord(value)) {
    return null
  }
  if (typeof value.football !== 'boolean' || typeof value.f1 !== 'boolean') {
    return null
  }
  return {
    football: value.football,
    f1: value.f1,
  }
}

function parseLlamaCppSettings(value: unknown): RuntimeSettings['llama_cpp'] | null {
  if (!isRecord(value)) {
    return null
  }
  if (typeof value.enabled !== 'boolean' || typeof value.host !== 'string') {
    return null
  }
  if (!value.host.trim()) {
    return null
  }
  const managed = value.managed === undefined ? false : value.managed
  if (typeof managed !== 'boolean') {
    return null
  }
  const executable_path =
    value.executable_path === undefined ? '' : value.executable_path
  const preset_path = value.preset_path === undefined ? '' : value.preset_path
  if (typeof executable_path !== 'string' || typeof preset_path !== 'string') {
    return null
  }
  return {
    enabled: value.enabled,
    managed,
    host: value.host.trim().replace(/\/$/, ''),
    executable_path,
    preset_path,
  }
}

function parseMcpSettings(value: unknown): McpSettings | null {
  if (!isRecord(value) || typeof value.enabled !== 'boolean' || !isRecord(value.servers)) {
    return null
  }
  const parsedServers: Partial<McpSettings['servers']> = {}
  for (const provider of MCP_PROVIDER_IDS) {
    const server = value.servers[provider]
    if (!isRecord(server) || typeof server.enabled !== 'boolean') {
      return null
    }
    parsedServers[provider] = { enabled: server.enabled }
  }
  return {
    enabled: value.enabled,
    servers: parsedServers as McpSettings['servers'],
  }
}

function parseToolProfiles(value: unknown): ToolProfilesSettings {
  if (!isRecord(value)) {
    return { custom_profiles: [], default_profile_by_agent: {} }
  }
  const custom_profiles = Array.isArray(value.custom_profiles)
    ? value.custom_profiles.flatMap((profile): ToolProfileSettings[] => {
      if (!isRecord(profile)) return []
      if (
        typeof profile.id !== 'string' ||
        typeof profile.name !== 'string' ||
        typeof profile.description !== 'string' ||
        !Array.isArray(profile.tool_names) ||
        !profile.tool_names.every((name) => typeof name === 'string') ||
        typeof profile.built_in !== 'boolean' ||
        typeof profile.dynamic !== 'boolean'
      ) {
        return []
      }
      return [{
        id: profile.id,
        name: profile.name,
        description: profile.description,
        tool_names: profile.tool_names,
        built_in: profile.built_in,
        dynamic: profile.dynamic,
      }]
    })
    : []
  const defaults = isRecord(value.default_profile_by_agent)
    ? Object.fromEntries(
      Object.entries(value.default_profile_by_agent).filter(
        ([agent, profileId]) => typeof agent === 'string' && typeof profileId === 'string',
      ),
    ) as Record<string, string>
    : {}
  return { custom_profiles, default_profile_by_agent: defaults }
}

function parseFootballSettings(value: unknown): FootballSettings {
  if (!isRecord(value) || !Array.isArray(value.teams)) {
    return { teams: [] }
  }

  const teams = value.teams.flatMap((team) => {
    if (!isRecord(team)) {
      return []
    }
    if (
      typeof team.id !== 'number' ||
      !Number.isInteger(team.id) ||
      team.id <= 0 ||
      typeof team.name !== 'string' ||
      !team.name.trim()
    ) {
      return []
    }
    return [{ id: team.id, name: team.name.trim() }]
  })

  return { teams: teams.slice(0, 3) }
}

function parseMarketSettings(value: unknown): MarketSettings {
  if (!isRecord(value) || !Array.isArray(value.symbols)) {
    return { symbols: [] }
  }

  const symbols = value.symbols
    .filter((symbol): symbol is string => typeof symbol === 'string' && symbol.trim().length > 0)
    .map((symbol) => symbol.trim().toUpperCase())
    .slice(0, 8)

  return { symbols }
}

function footballTeamsEqual(
  left: FootballSettings['teams'],
  right: FootballSettings['teams'],
): boolean {
  return (
    left.length === right.length &&
    left.every((team, index) => team.id === right[index]?.id && team.name === right[index]?.name)
  )
}

function marketSymbolsEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((symbol, index) => symbol === right[index])
}

function parseRuntimeSettings(value: unknown): RuntimeSettings | null {
  if (!isRecord(value)) {
    return null
  }

  const features = parseFeatures(value.features)
  const modules = parseModules(value.modules)
  const football = parseFootballSettings(value.football)
  const market = parseMarketSettings(value.market)
  const mcp = parseMcpSettings(value.mcp)
  const hasToolProfiles = isRecord(value.tool_profiles)
  const tool_profiles = parseToolProfiles(value.tool_profiles)
  const llama_cpp = parseLlamaCppSettings(value.llama_cpp)
  if (
    !features ||
    !modules ||
    !mcp ||
    !llama_cpp ||
    !isRecord(value.ask_apex) ||
    !isRecord(value.briefing) ||
    !isRecord(value.voice)
  ) {
    return null
  }

  if (typeof value.ask_apex.enabled !== 'boolean') {
    return null
  }
  if (!isAgentRuntime(value.ask_apex.runtime)) {
    return null
  }
  if (!isCloudSettingsAgent(value.ask_apex.cloud_agent)) {
    return null
  }
  if (!isCloudEffort(value.ask_apex.effort)) {
    return null
  }
  if (!isLocalSettingsAgent(value.ask_apex.local_agent)) {
    return null
  }
  const localContextWindows = parseLocalContextWindows(
    value.ask_apex.local_context_windows,
  )
  if (!localContextWindows) {
    return null
  }
  if (typeof value.ask_apex.neofelis_google_search_enabled !== 'boolean') {
    return null
  }
  if (typeof value.ask_apex.neofelis_google_maps_enabled !== 'boolean') {
    return null
  }
  if (typeof value.ask_apex.delphinus_x_search_enabled !== 'boolean') {
    return null
  }
  if (typeof value.ask_apex.orcinus_x_search_enabled !== 'boolean') {
    return null
  }
  if (!isBriefingMode(value.briefing.default_mode)) {
    return null
  }
  if (
    !isTtsEngine(value.voice.engine) ||
    !isVoiceGender(value.voice.gender) ||
    !isVoiceMode(value.voice.mode)
  ) {
    return null
  }

  return {
    user_designation:
      typeof value.user_designation === 'string' ? value.user_designation : '',
    features,
    modules,
    football,
    market,
    ask_apex: {
      enabled: value.ask_apex.enabled,
      runtime: value.ask_apex.runtime,
      cloud_agent: value.ask_apex.cloud_agent,
      effort: value.ask_apex.effort,
      local_agent: value.ask_apex.local_agent,
      local_context_windows: localContextWindows,
      neofelis_google_search_enabled: value.ask_apex.neofelis_google_search_enabled,
      neofelis_google_maps_enabled: value.ask_apex.neofelis_google_maps_enabled,
      delphinus_x_search_enabled: value.ask_apex.delphinus_x_search_enabled,
      orcinus_x_search_enabled: value.ask_apex.orcinus_x_search_enabled,
    },
    ...(hasToolProfiles ? { tool_profiles } : {}),
    briefing: {
      default_mode: value.briefing.default_mode,
    },
    voice: {
      engine: value.voice.engine,
      gender: value.voice.gender,
      mode: value.voice.mode,
    },
    mcp,
    llama_cpp,
  }
}

export function resolveAgentKey(settings: RuntimeSettings['ask_apex']): AgentKey {
  return settings.runtime === 'local' ? settings.local_agent : settings.cloud_agent
}

export function cloneRuntimeSettings(settings: RuntimeSettings): RuntimeSettings {
  return {
    user_designation: settings.user_designation,
    features: { ...settings.features },
    modules: { ...settings.modules },
    football: {
      teams: settings.football.teams.map((team) => ({ ...team })),
    },
    market: {
      symbols: [...settings.market.symbols],
    },
    ask_apex: {
      ...settings.ask_apex,
      local_context_windows: { ...settings.ask_apex.local_context_windows },
    },
    ...(settings.tool_profiles
      ? {
          tool_profiles: {
            custom_profiles: settings.tool_profiles.custom_profiles.map((profile) => ({
              ...profile,
              tool_names: [...profile.tool_names],
            })),
            default_profile_by_agent: {
              ...settings.tool_profiles.default_profile_by_agent,
            },
          },
        }
      : {}),
    briefing: { ...settings.briefing },
    voice: { ...settings.voice },
    mcp: {
      enabled: settings.mcp.enabled,
      servers: {
        github: { ...settings.mcp.servers.github },
        brave: { ...settings.mcp.servers.brave },
        alphavantage: { ...settings.mcp.servers.alphavantage },
      },
    },
    llama_cpp: { ...settings.llama_cpp },
  }
}

export function parseSettingsResponse(body: unknown): SettingsResponse | null {
  if (!isRecord(body)) {
    return null
  }

  const settings = parseRuntimeSettings(body.settings)
  if (!settings) {
    return null
  }

  if (typeof body.schema_version !== 'number') {
    return null
  }
  if (typeof body.local_file_present !== 'boolean') {
    return null
  }
  if (typeof body.local_override_active !== 'boolean') {
    return null
  }
  if (body.load_warning !== null && typeof body.load_warning !== 'string') {
    return null
  }
  if (typeof body.dev_mode_active !== 'boolean') {
    return null
  }
  if (typeof body.demo_mode_active !== 'boolean') {
    return null
  }

  return {
    schema_version: body.schema_version,
    settings,
    local_file_present: body.local_file_present,
    local_override_active: body.local_override_active,
    load_warning: body.load_warning,
    dev_mode_active: body.dev_mode_active,
    demo_mode_active: body.demo_mode_active,
  }
}

function diffSection<T extends object>(
  baseline: T,
  draft: T,
): Partial<T> | undefined {
  const patch: Partial<T> = {}
  let dirty = false

  for (const key of Object.keys(draft) as Array<keyof T>) {
    if (
      draft[key] !== baseline[key] &&
      JSON.stringify(draft[key]) !== JSON.stringify(baseline[key])
    ) {
      patch[key] = draft[key]
      dirty = true
    }
  }

  return dirty ? patch : undefined
}

export function diffSettingsPatch(
  baseline: RuntimeSettings,
  draft: RuntimeSettings,
): SettingsPatch {
  const patch: SettingsPatch = {}

  if (baseline.user_designation !== draft.user_designation) {
    patch.user_designation = draft.user_designation
  }

  const features = diffSection(baseline.features, draft.features)
  if (features) {
    patch.features = features
  }

  const modules = diffSection(baseline.modules, draft.modules)
  if (modules) {
    patch.modules = modules
  }

  if (!footballTeamsEqual(baseline.football.teams, draft.football.teams)) {
    patch.football = {
      teams: draft.football.teams
        .filter((team) => team.id > 0 && team.name.trim().length > 0)
        .map((team) => ({ id: team.id, name: team.name.trim() })),
    }
  }

  if (!marketSymbolsEqual(baseline.market.symbols, draft.market.symbols)) {
    patch.market = {
      symbols: [...draft.market.symbols],
    }
  }

  const askApex = diffSection(baseline.ask_apex, draft.ask_apex)
  if (askApex) {
    patch.ask_apex = askApex
  }

  if (JSON.stringify(baseline.tool_profiles) !== JSON.stringify(draft.tool_profiles)) {
    const draftProfiles = draft.tool_profiles ?? {
      custom_profiles: [],
      default_profile_by_agent: {},
    }
    patch.tool_profiles = {
      custom_profiles: draftProfiles.custom_profiles.map((profile) => ({
        ...profile,
        tool_names: [...profile.tool_names],
      })),
      default_profile_by_agent: { ...draftProfiles.default_profile_by_agent },
    }
  }

  const briefing = diffSection(baseline.briefing, draft.briefing)
  if (briefing) {
    patch.briefing = briefing
  }

  const voice = diffSection(baseline.voice, draft.voice)
  if (voice) {
    patch.voice = voice
  }

  const mcpServers: NonNullable<SettingsPatch['mcp']>['servers'] = {}
  for (const provider of MCP_PROVIDER_IDS) {
    if (baseline.mcp.servers[provider].enabled !== draft.mcp.servers[provider].enabled) {
      mcpServers[provider] = { enabled: draft.mcp.servers[provider].enabled }
    }
  }
  if (
    baseline.mcp.enabled !== draft.mcp.enabled ||
    Object.keys(mcpServers).length > 0
  ) {
    patch.mcp = {}
    if (baseline.mcp.enabled !== draft.mcp.enabled) {
      patch.mcp.enabled = draft.mcp.enabled
    }
    if (Object.keys(mcpServers).length > 0) {
      patch.mcp.servers = mcpServers
    }
  }

  const llamaCpp = diffSection(baseline.llama_cpp, draft.llama_cpp)
  if (llamaCpp) {
    patch.llama_cpp = llamaCpp
  }

  return patch
}

export function isSettingsPatchEmpty(patch: SettingsPatch): boolean {
  return (
    patch.user_designation === undefined &&
    patch.features === undefined &&
    patch.modules === undefined &&
    patch.football === undefined &&
    patch.market === undefined &&
    patch.ask_apex === undefined &&
    patch.briefing === undefined &&
    patch.voice === undefined &&
    patch.mcp === undefined &&
    patch.llama_cpp === undefined
  )
}

export function settingsAreEqual(a: RuntimeSettings, b: RuntimeSettings): boolean {
  return isSettingsPatchEmpty(diffSettingsPatch(a, b))
}

export function buildSettingsTimingRuntime(input: {
  status: SystemState
  pipelineStep: number | null
  isSpeaking: boolean
  isCortexQuerying: boolean
}): SettingsTimingRuntime {
  const step = input.pipelineStep
  const briefingActive =
    input.status === 'loading' || (step !== null && step >= 1 && step <= 4)

  return {
    briefingActive,
    pipelineStep: step,
    isSpeaking: input.isSpeaking,
    isCortexQuerying: input.isCortexQuerying,
  }
}

export function resolveEffectiveTiming(
  group: SettingsTimingFieldGroup,
  runtime: SettingsTimingRuntime,
): SettingsEffectiveTiming {
  if (group === 'features' || group === 'modules' || group === 'football') {
    return runtime.briefingActive ? 'Applies next briefing' : 'Active'
  }

  if (group === 'market') {
    return 'Active'
  }

  if (group === 'ask_apex') {
    return runtime.isCortexQuerying ? 'Applies next response' : 'Active'
  }

  if (group === 'briefing') {
    return runtime.briefingActive ? 'Applies next briefing' : 'Active'
  }

  if (group === 'mcp' || group === 'llama_cpp') {
    return 'Active'
  }

  // voice
  if (runtime.isSpeaking) {
    return 'Applies next delivery'
  }

  const step = runtime.pipelineStep
  if (step !== null && step >= 1 && step <= 3) {
    return 'Applies this delivery'
  }

  return 'Active'
}

export function parseMcpStatusResponse(body: unknown): McpStatusResponse | null {
  if (
    !isRecord(body) ||
    typeof body.enabled !== 'boolean' ||
    typeof body.status !== 'string' ||
    !(VALID_MCP_STATUSES as readonly string[]).includes(body.status) ||
    typeof body.reason !== 'string' ||
    !Array.isArray(body.servers)
  ) {
    return null
  }
  const servers = body.servers.map((server) => {
    if (
      !isRecord(server) ||
      typeof server.id !== 'string' ||
      typeof server.enabled !== 'boolean' ||
      (server.transport !== 'http' && server.transport !== 'stdio') ||
      typeof server.status !== 'string' ||
      !(VALID_MCP_STATUSES as readonly string[]).includes(server.status) ||
      typeof server.reason !== 'string' ||
      !Array.isArray(server.registered_tools) ||
      !server.registered_tools.every((tool) => typeof tool === 'string')
    ) {
      return null
    }
    return {
      id: server.id,
      enabled: server.enabled,
      transport: server.transport,
      status: server.status,
      reason: server.reason,
      registered_tools: server.registered_tools,
    }
  })
  if (servers.some((server) => server === null)) {
    return null
  }
  return {
    enabled: body.enabled,
    status: body.status as McpStatusResponse['status'],
    reason: body.reason,
    servers: servers as McpStatusResponse['servers'],
  }
}

const VALID_LLAMA_CPP_SERVER_STATES = [
  'disabled',
  'external_connected',
  'managed_running',
  'starting',
  'managed_stopped',
  'startup_failed',
] as const

const VALID_LLAMA_CPP_OWNERSHIP = ['none', 'external', 'apex'] as const

export function parseLlamaCppServerStatusResponse(
  body: unknown,
): LlamaCppServerStatusResponse | null {
  if (
    !isRecord(body) ||
    typeof body.enabled !== 'boolean' ||
    typeof body.managed !== 'boolean' ||
    typeof body.ownership !== 'string' ||
    !(VALID_LLAMA_CPP_OWNERSHIP as readonly string[]).includes(body.ownership) ||
    typeof body.state !== 'string' ||
    !(VALID_LLAMA_CPP_SERVER_STATES as readonly string[]).includes(body.state) ||
    !(body.last_error === null || typeof body.last_error === 'string')
  ) {
    return null
  }
  return {
    enabled: body.enabled,
    managed: body.managed,
    ownership: body.ownership as LlamaCppServerStatusResponse['ownership'],
    state: body.state as LlamaCppServerStatusResponse['state'],
    last_error: body.last_error,
  }
}

export async function extractSettingsErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (isRecord(body) && typeof body.detail === 'string' && body.detail.trim()) {
      return body.detail
    }
    if (isRecord(body) && Array.isArray(body.detail)) {
      return `Settings request failed (${response.status})`
    }
  } catch {
    // Fall through to status-based message.
  }
  return `Settings request failed (${response.status})`
}
