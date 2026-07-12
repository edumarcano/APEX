import type { AssistantProfile, SystemState, TtsEngine } from '../types/telemetry'
import type {
  FeaturesSettings,
  ModulesSettings,
  RuntimeSettings,
  SettingsEffectiveTiming,
  SettingsPatch,
  SettingsResponse,
  SettingsTimingFieldGroup,
  SettingsTimingRuntime,
  VoiceGender,
} from '../types/settings'

const VALID_ASSISTANT_PROFILES: readonly AssistantProfile[] = [
  'comet',
  'nova',
  'pulsar',
  'lynx',
  'acinonyx',
  'neofelis',
]

const VALID_TTS_ENGINES: readonly TtsEngine[] = ['google', 'kokoro', 'pyttsx3']
const VALID_VOICE_GENDERS: readonly VoiceGender[] = ['male', 'female']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAssistantProfile(value: unknown): value is AssistantProfile {
  return (
    typeof value === 'string' &&
    (VALID_ASSISTANT_PROFILES as readonly string[]).includes(value)
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

function parseBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function parseFeatures(value: unknown): FeaturesSettings | null {
  if (!isRecord(value)) {
    return null
  }
  return {
    weather: parseBoolean(value.weather, false),
    sports: parseBoolean(value.sports, false),
    news: parseBoolean(value.news, false),
    email: parseBoolean(value.email, false),
    calendar: parseBoolean(value.calendar, false),
  }
}

function parseModules(value: unknown): ModulesSettings | null {
  if (!isRecord(value)) {
    return null
  }
  return {
    football: parseBoolean(value.football, false),
    f1: parseBoolean(value.f1, false),
  }
}

function parseRuntimeSettings(value: unknown): RuntimeSettings | null {
  if (!isRecord(value)) {
    return null
  }

  const features = parseFeatures(value.features)
  const modules = parseModules(value.modules)
  if (!features || !modules || !isRecord(value.assistant) || !isRecord(value.voice)) {
    return null
  }

  if (!isAssistantProfile(value.assistant.default_profile)) {
    return null
  }
  if (!isTtsEngine(value.voice.engine) || !isVoiceGender(value.voice.gender)) {
    return null
  }

  return {
    features,
    modules,
    assistant: {
      enabled: parseBoolean(value.assistant.enabled, true),
      default_profile: value.assistant.default_profile,
    },
    voice: {
      engine: value.voice.engine,
      gender: value.voice.gender,
    },
  }
}

export function cloneRuntimeSettings(settings: RuntimeSettings): RuntimeSettings {
  return {
    features: { ...settings.features },
    modules: { ...settings.modules },
    assistant: { ...settings.assistant },
    voice: { ...settings.voice },
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

  const voice = diffSection(baseline.voice, draft.voice)
  if (voice) {
    patch.voice = voice
  }

  return patch
}

export function isSettingsPatchEmpty(patch: SettingsPatch): boolean {
  return (
    patch.features === undefined &&
    patch.modules === undefined &&
    patch.assistant === undefined &&
    patch.voice === undefined
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

  if (group === 'assistant') {
    return runtime.isAssistantQuerying ? 'Applies next response' : 'Active'
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
