import type {
  AgentRuntime,
  CloudEffort,
  CloudSettingsAgent,
  LocalSettingsAgent,
  TtsEngine,
} from './telemetry'
import type { McpProviderId } from '../lib/mcpProviders'

export type { McpProviderId } from '../lib/mcpProviders'

export type VoiceGender = 'male' | 'female'
export type VoiceMode = 'off' | 'manual' | 'automatic'
export type BriefingMode = 'panthera' | 'mus' | 'sorex' | 'structured_digest'
export type ApodemusContextWindow = 4096 | 8192 | 16384 | 32768

export interface LlamaCppSettings {
  enabled: boolean
  host: string
}

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

export interface AskApexSettings {
  enabled: boolean
  runtime: AgentRuntime
  cloud_agent: CloudSettingsAgent
  effort: CloudEffort
  local_agent: LocalSettingsAgent
  apodemus_context_window: ApodemusContextWindow
  neofelis_google_search_enabled: boolean
  neofelis_google_maps_enabled: boolean
  delphinus_x_search_enabled: boolean
  orcinus_x_search_enabled: boolean
}

export interface BriefingSettings {
  default_mode: BriefingMode
}

export interface VoiceSettings {
  engine: TtsEngine
  gender: VoiceGender
  mode: VoiceMode
}

export interface McpServerEnablementSettings {
  enabled: boolean
}

export interface McpSettings {
  enabled: boolean
  servers: Record<McpProviderId, McpServerEnablementSettings>
}

export interface RuntimeSettings {
  user_designation: string
  features: FeaturesSettings
  modules: ModulesSettings
  ask_apex: AskApexSettings
  briefing: BriefingSettings
  voice: VoiceSettings
  mcp: McpSettings
  llama_cpp: LlamaCppSettings
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

export interface AskApexPatch {
  enabled?: boolean
  runtime?: AgentRuntime
  cloud_agent?: CloudSettingsAgent
  effort?: CloudEffort
  local_agent?: LocalSettingsAgent
  apodemus_context_window?: ApodemusContextWindow
  neofelis_google_search_enabled?: boolean
  neofelis_google_maps_enabled?: boolean
  delphinus_x_search_enabled?: boolean
  orcinus_x_search_enabled?: boolean
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

export interface LlamaCppPatch {
  enabled?: boolean
  host?: string
}

export interface SettingsPatch {
  user_designation?: string
  features?: FeaturesPatch
  modules?: ModulesPatch
  ask_apex?: AskApexPatch
  briefing?: BriefingPatch
  voice?: VoicePatch
  mcp?: McpPatch
  llama_cpp?: LlamaCppPatch
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
  | 'ask_apex'
  | 'briefing'
  | 'voice'
  | 'mcp'
  | 'llama_cpp'

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
  isCortexQuerying: boolean
}
