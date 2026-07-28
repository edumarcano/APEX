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

export type McpProviderId = 'github' | 'brave' | 'alphavantage'

export interface McpServerEnablementSettings {
  enabled: boolean
}

export interface McpSettings {
  enabled: boolean
  servers: Record<McpProviderId, McpServerEnablementSettings>
}

export interface RuntimeSettings {
  features: FeaturesSettings
  modules: ModulesSettings
  assistant: AssistantSettings
  briefing: BriefingSettings
  voice: VoiceSettings
  mcp: McpSettings
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

export interface McpPatch {
  enabled?: boolean
  servers?: Partial<Record<McpProviderId, McpServerEnablementPatch>>
}

export interface McpServerEnablementPatch {
  enabled?: boolean
}

export interface SettingsPatch {
  features?: FeaturesPatch
  modules?: ModulesPatch
  assistant?: AssistantPatch
  briefing?: BriefingPatch
  voice?: VoicePatch
  mcp?: McpPatch
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
  | 'mcp'

export type McpRuntimeStatus =
  | 'configured'
  | 'connected'
  | 'degraded'
  | 'disabled'
  | 'authentication-required'

export interface McpServerStatus {
  id: string
  enabled: boolean
  transport: 'http' | 'stdio'
  status: McpRuntimeStatus
  reason: string
  registered_tools: string[]
}

export interface McpStatusResponse {
  enabled: boolean
  status: McpRuntimeStatus
  reason: string
  servers: McpServerStatus[]
}

export interface SettingsTimingRuntime {
  briefingActive: boolean
  pipelineStep: number | null
  isSpeaking: boolean
  isAssistantQuerying: boolean
}
