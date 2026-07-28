import type { AssistantProfile, SystemState, TtsEngine } from '../types/telemetry'
import type {
  BriefingMode,
  FeaturesSettings,
  ModulesSettings,
  McpSettings,
  McpStatusResponse,
  RuntimeSettings,
  SettingsEffectiveTiming,
  SettingsPatch,
  SettingsResponse,
  SettingsTimingFieldGroup,
  SettingsTimingRuntime,
  VoiceGender,
  VoiceMode,
} from '../types/settings'
import { MCP_PROVIDER_IDS } from './mcpProviders'

const VALID_ASSISTANT_PROFILES: readonly AssistantProfile[] = [
  'comet',
  'nova',
  'pulsar',
  'lynx',
  'acinonyx',
  'neofelis',
]

const VALID_BRIEFING_MODES: readonly BriefingMode[] = [
  'comet',
  'lynx',
  'acinonyx',
  'neofelis',
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

function isAssistantProfile(value: unknown): value is AssistantProfile {
  return (
    typeof value === 'string' &&
    (VALID_ASSISTANT_PROFILES as readonly string[]).includes(value)
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

function parseRuntimeSettings(value: unknown): RuntimeSettings | null {
  if (!isRecord(value)) {
    return null
  }

  const features = parseFeatures(value.features)
  const modules = parseModules(value.modules)
  const mcp = parseMcpSettings(value.mcp)
  if (
    !features ||
    !modules ||
    !mcp ||
    !isRecord(value.assistant) ||
    !isRecord(value.briefing) ||
    !isRecord(value.voice)
  ) {
    return null
  }

  if (typeof value.assistant.enabled !== 'boolean') {
    return null
  }
  if (!isAssistantProfile(value.assistant.default_profile)) {
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
    features,
    modules,
    assistant: {
      enabled: value.assistant.enabled,
      default_profile: value.assistant.default_profile,
    },
    briefing: {
      default_mode: value.briefing.default_mode,
    },
    voice: {
      engine: value.voice.engine,
      gender: value.voice.gender,
      mode: value.voice.mode,
    },
    mcp,
  }
}

export function cloneRuntimeSettings(settings: RuntimeSettings): RuntimeSettings {
  return {
    features: { ...settings.features },
    modules: { ...settings.modules },
    assistant: { ...settings.assistant },
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
    if (draft[key] !== baseline[key]) {
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

  const features = diffSection(baseline.features, draft.features)
  if (features) {
    patch.features = features
  }

  const modules = diffSection(baseline.modules, draft.modules)
  if (modules) {
    patch.modules = modules
  }

  const assistant = diffSection(baseline.assistant, draft.assistant)
  if (assistant) {
    patch.assistant = assistant
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

  return patch
}

export function isSettingsPatchEmpty(patch: SettingsPatch): boolean {
  return (
    patch.features === undefined &&
    patch.modules === undefined &&
    patch.assistant === undefined &&
    patch.briefing === undefined &&
    patch.voice === undefined &&
    patch.mcp === undefined
  )
}

export function settingsAreEqual(a: RuntimeSettings, b: RuntimeSettings): boolean {
  return isSettingsPatchEmpty(diffSettingsPatch(a, b))
}

export function buildSettingsTimingRuntime(input: {
  status: SystemState
  pipelineStep: number | null
  isSpeaking: boolean
  isAssistantQuerying: boolean
}): SettingsTimingRuntime {
  const step = input.pipelineStep
  const briefingActive =
    input.status === 'loading' || (step !== null && step >= 1 && step <= 4)

  return {
    briefingActive,
    pipelineStep: step,
    isSpeaking: input.isSpeaking,
    isAssistantQuerying: input.isAssistantQuerying,
  }
}

export function resolveEffectiveTiming(
  group: SettingsTimingFieldGroup,
  runtime: SettingsTimingRuntime,
): SettingsEffectiveTiming {
  if (group === 'features' || group === 'modules') {
    return runtime.briefingActive ? 'Applies next briefing' : 'Active'
  }

  if (group === 'market') {
    return 'Active'
  }

  if (group === 'assistant') {
    return runtime.isAssistantQuerying ? 'Applies next response' : 'Active'
  }

  if (group === 'briefing') {
    return runtime.briefingActive ? 'Applies next briefing' : 'Active'
  }

  if (group === 'mcp') {
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
