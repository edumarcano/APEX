import type { AssistantProfile, TtsEngine } from './telemetry'

export type VoiceGender = 'male' | 'female'

export interface FeaturesSettings {
  weather: boolean
  sports: boolean
  news: boolean
  email: boolean
  calendar: boolean
}

export interface ModulesSettings {
  football: boolean
  f1: boolean
}

export interface AssistantSettings {
  enabled: boolean
  default_profile: AssistantProfile
}

export interface VoiceSettings {
  engine: TtsEngine
  gender: VoiceGender
}

export interface RuntimeSettings {
  features: FeaturesSettings
  modules: ModulesSettings
  assistant: AssistantSettings
  voice: VoiceSettings
}

export interface FeaturesPatch {
  weather?: boolean
  sports?: boolean
  news?: boolean
  email?: boolean
  calendar?: boolean
}

export interface ModulesPatch {
  football?: boolean
  f1?: boolean
}

export interface AssistantPatch {
  enabled?: boolean
  default_profile?: AssistantProfile
}

export interface VoicePatch {
  engine?: TtsEngine
  gender?: VoiceGender
}

export interface SettingsPatch {
  features?: FeaturesPatch
  modules?: ModulesPatch
  assistant?: AssistantPatch
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

export type SettingsTimingFieldGroup = 'features' | 'modules' | 'assistant' | 'voice'

export interface SettingsTimingRuntime {
  briefingActive: boolean
  pipelineStep: number | null
  isSpeaking: boolean
  isAssistantQuerying: boolean
}
