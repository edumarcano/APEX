import type { AssistantProfile, TtsEngine } from './telemetry'

export type VoiceGender = 'male' | 'female'
export type VoiceMode = 'off' | 'manual' | 'automatic'
export type BriefingMode =
  | 'comet'
  | 'lynx'
  | 'acinonyx'
  | 'neofelis'
  | 'structured_digest'

export interface FeaturesSettings {
  weather: boolean
  sports: boolean
  news: boolean
  email: boolean
  calendar: boolean
  market: boolean
}

export interface ModulesSettings {
  football: boolean
  f1: boolean
}

export interface AssistantSettings {
  enabled: boolean
  default_profile: AssistantProfile
}

export interface BriefingSettings {
  default_mode: BriefingMode
}

export interface VoiceSettings {
  engine: TtsEngine
  gender: VoiceGender
  mode: VoiceMode
}

export interface RuntimeSettings {
  features: FeaturesSettings
  modules: ModulesSettings
  assistant: AssistantSettings
  briefing: BriefingSettings
  voice: VoiceSettings
}

export interface FeaturesPatch {
  weather?: boolean
  sports?: boolean
  news?: boolean
  email?: boolean
  calendar?: boolean
  market?: boolean
}

export interface ModulesPatch {
  football?: boolean
  f1?: boolean
}

export interface AssistantPatch {
  enabled?: boolean
  default_profile?: AssistantProfile
}

export interface BriefingPatch {
  default_mode?: BriefingMode
}

export interface VoicePatch {
  engine?: TtsEngine
  gender?: VoiceGender
  mode?: VoiceMode
}

export interface SettingsPatch {
  features?: FeaturesPatch
  modules?: ModulesPatch
  assistant?: AssistantPatch
  briefing?: BriefingPatch
  voice?: VoicePatch
}

export interface SettingsResponse {
  schema_version: number
  settings: RuntimeSettings
  local_file_present: boolean
  local_override_active: boolean
  load_warning: string | null
  dev_mode_active: boolean
  demo_mode_active: boolean
}

export type SettingsEffectiveTiming =
  | 'Active'
  | 'Applies this delivery'
  | 'Applies next briefing'
  | 'Applies next response'
  | 'Applies next delivery'

export type SettingsTimingFieldGroup =
  | 'features'
  | 'market'
  | 'modules'
  | 'assistant'
  | 'briefing'
  | 'voice'

export interface SettingsTimingRuntime {
  briefingActive: boolean
  pipelineStep: number | null
  isSpeaking: boolean
  isAssistantQuerying: boolean
}
