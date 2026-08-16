import type {
  AgentKey,
  CloudEffort,
  CloudProvider,
  LocalReasoningMode,
  LocalRuntime,
  TtsEngine,
} from './telemetry'

export type { LocalReasoningMode } from './telemetry'
import type { McpProviderId } from '../lib/mcpProviders'

export type { McpProviderId } from '../lib/mcpProviders'

export type VoiceGender = 'male' | 'female'
export type VoiceMode = 'off' | 'manual' | 'automatic'
export type BriefingMode = 'panthera' | 'lynx' | 'structured_digest'

export interface LlamaCppSettings {
  enabled: boolean
  managed: boolean
  host: string
  executable_path: string
  preset_path: string
}

export interface MicrosoftTodoSettings {
  reminder_list_id: string
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

export interface FootballTeamSettings {
  id: number
  name: string
}

export interface FootballSettings {
  teams: FootballTeamSettings[]
}

export interface MarketSettings {
  symbols: string[]
}

export interface PantheraHostedToolsSettings {
  google_search: boolean
  google_maps: boolean
  x_search: boolean
}

export interface PantheraSettings {
  provider: CloudProvider
  model: string
  effort: CloudEffort
  hosted_tools: PantheraHostedToolsSettings
}

export interface LynxSettings {
  runtime: LocalRuntime
  model: string
  context_window: number
  reasoning_mode: LocalReasoningMode
}

export interface AgentSettings {
  enabled: boolean
  agent: AgentKey
  sandbox_mode: boolean
  panthera: PantheraSettings
  lynx: LynxSettings
}

export interface ToolProfileSettings {
  id: string
  name: string
  description: string
  tool_names: string[]
  built_in: boolean
  dynamic: boolean
}

export interface ToolProfilesSettings {
  custom_profiles: ToolProfileSettings[]
  default_profile_by_agent: Record<string, string>
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
  football: FootballSettings
  market: MarketSettings
  ask_apex: AgentSettings
  tool_profiles?: ToolProfilesSettings
  briefing: BriefingSettings
  voice: VoiceSettings
  mcp: McpSettings
  llama_cpp: LlamaCppSettings
  microsoft_todo: MicrosoftTodoSettings
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

export interface FootballTeamPatch {
  id: number
  name: string
}

export interface FootballPatch {
  teams?: FootballTeamPatch[]
}

export interface MarketPatch {
  symbols?: string[]
}

export interface PantheraHostedToolsPatch {
  google_search?: boolean
  google_maps?: boolean
  x_search?: boolean
}

export interface PantheraSettingsPatch {
  provider?: CloudProvider
  model?: string
  effort?: CloudEffort
  hosted_tools?: PantheraHostedToolsPatch
}

export interface LynxSettingsPatch {
  runtime?: LocalRuntime
  model?: string
  context_window?: number
  reasoning_mode?: LocalReasoningMode
}

export interface AgentSettingsPatch {
  enabled?: boolean
  agent?: AgentKey
  sandbox_mode?: boolean
  panthera?: PantheraSettingsPatch
  lynx?: LynxSettingsPatch
}

export interface ToolProfilesPatch {
  custom_profiles?: ToolProfileSettings[]
  default_profile_by_agent?: Record<string, string>
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
  managed?: boolean
  host?: string
  executable_path?: string
  preset_path?: string
}

export interface MicrosoftTodoPatch {
  reminder_list_id?: string
}

export type LlamaCppServerState =
  | 'disabled'
  | 'external_connected'
  | 'managed_running'
  | 'starting'
  | 'managed_stopped'
  | 'startup_failed'

export type LlamaCppServerOwnership = 'none' | 'external' | 'apex'

export interface LlamaCppServerStatusResponse {
  enabled: boolean
  managed: boolean
  ownership: LlamaCppServerOwnership
  state: LlamaCppServerState
  last_error: string | null
}


export interface SettingsPatch {
  user_designation?: string
  features?: FeaturesPatch
  modules?: ModulesPatch
  football?: FootballPatch
  market?: MarketPatch
  ask_apex?: AgentSettingsPatch
  tool_profiles?: ToolProfilesPatch
  briefing?: BriefingPatch
  voice?: VoicePatch
  mcp?: McpPatch
  llama_cpp?: LlamaCppPatch
  microsoft_todo?: MicrosoftTodoPatch
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
  | 'football'
  | 'modules'
  | 'agent_queries'
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
