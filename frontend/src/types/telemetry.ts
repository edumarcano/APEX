export type TtsEngine = 'google' | 'kokoro' | 'pyttsx3'

export interface PipelineState {
  step: number
  label: string
  timestamp: string
  is_speaking: boolean
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
  synthesis?: SynthesisLiveState | null
}

export type SynthesisProvider = 'gemini' | 'ollama' | 'raw' | 'demo'
export type SynthesisProfile = 'comet' | 'lynx' | 'acinonyx' | 'neofelis'
export type SynthesisStrategy = 'cloud' | 'local' | 'raw' | 'demo'

export interface SynthesisLiveState {
  phase: 'idle' | 'loading' | 'ready' | 'generating' | 'fallback' | 'complete'
  provider: SynthesisProvider | null
  profile: SynthesisProfile | null
  loading: boolean
  fallback_reason: string | null
}

export interface SystemDiagnostics {
  cpu: number | null
  cpu_freq: number | null
  ram: number | null
  ram_used: number | null
  ram_total: number | null
  disk: number | null
  disk_used: number | null
  disk_total: number | null
}

export const DEFAULT_SYSTEM_DIAGNOSTICS: SystemDiagnostics = {
  cpu: null,
  cpu_freq: null,
  ram: null,
  ram_used: null,
  ram_total: null,
  disk: null,
  disk_used: null,
  disk_total: null,
}

export interface ActiveReminder {
  id: number
  note: string
}

export interface ToolOutputItem {
  name: string
  status: string
  duration_ms: number
  output: unknown
}

export interface AgentMessage {
  role: 'user' | 'model' | 'tool'
  content?: string
  tool_outputs?: ToolOutputItem[]
}

export type WeatherConditionArchetype =
  | 'clear_day'
  | 'clear_night'
  | 'clouds'
  | 'rain'
  | 'thunderstorm'

export type AgentCloudProfile = 'comet' | 'nova' | 'pulsar'

export type AssistantProfile =
  | 'comet'
  | 'nova'
  | 'pulsar'
  | 'lynx'
  | 'acinonyx'
  | 'neofelis'

export type ProfileAvailabilityStatus =
  | 'available'
  | 'unknown'
  | 'disabled'
  | 'ollama_unreachable'
  | 'model_not_installed'
  | 'insufficient_ram'
  | 'cpu_overloaded'

export type ProfileStability = 'stable' | 'preview'

export interface LoadedOllamaModelStatus {
  name: string
  model: string
  size_bytes: number | null
  size_vram_bytes: number | null
  processor: string | null
  context: string | null
  expires_at: string | null
}

export interface AgentProfileStatus {
  key: AssistantProfile
  display_name: string
  provider: 'ollama' | 'gemini'
  tier: string
  stability: ProfileStability
  /** Gemini thinking level; null/omitted for Ollama or older API responses. */
  thinking_level?: string | null
  status: ProfileAvailabilityStatus
  active: boolean
  loading: boolean
  reason: string | null
  idle_unload_remaining_seconds: number | null
  loaded_model: LoadedOllamaModelStatus | null
}

export interface DigestPayload {
  insights: string[]
  sync_health_score?: number
  confidence_score?: number
  failed_connectors?: string[]
  connector_health?: ConnectorHealthEntry[]
}

export type ConnectorHealthStatus = 'healthy' | 'degraded' | 'unavailable' | 'disabled'
export type ConnectorFreshness = 'live' | 'fresh_cache' | 'stale' | 'none'

export interface ConnectorHealthEntry {
  name: string
  status: ConnectorHealthStatus
  freshness?: ConnectorFreshness
  reason_code?: string
  observed_at?: string | null
}

export interface TelemetryModuleEntry {
  name: string
  status: ConnectorHealthStatus
  freshness: ConnectorFreshness
  reason_code: string
  observed_at: string | null
  display_text: string
  data: Record<string, unknown>
}

export interface TelemetrySnapshot {
  snapshot_id: string
  collected_at: string
  modules: Record<string, TelemetryModuleEntry>
  sync_health_score: number
  connector_health: ConnectorHealthEntry[]
  failed_connectors: string[]
}

export interface TelemetryRefreshRequest {
  connectors?: string[] | null
  force?: boolean
}

export type PreflightOperation =
  | 'activate'
  | 'activate_with_briefing'
  | 'refresh_telemetry'
  | 'generate_briefing'
  | 'assistant_query'

export type PreflightWarningCode =
  | 'outside_configured_network'
  | 'network_trust_unknown'
  | 'running_on_battery'
  | 'rapid_connector_refresh'
  | 'cloud_data_disclosure'
  | 'high_resource_local_profile'

export type PreflightBlockerCode =
  | 'missing_credentials'
  | 'model_unreachable'
  | 'model_not_installed'
  | 'concurrent_local_execution'
  | 'insufficient_ram'
  | 'cpu_overloaded'
  | 'database_failure'
  | 'configuration_failure'
  | 'invalid_input'
  | 'model_load_failure'

export interface PreflightWarning {
  code: PreflightWarningCode
  message: string
}

export interface PreflightBlocker {
  code: PreflightBlockerCode
  message: string
}

export interface PreflightRequest {
  operation: PreflightOperation
  connectors?: string[] | null
  synthesis_profile?: string | null
  force?: boolean
  involves_cloud?: boolean
  acknowledged_warnings?: string[]
  cloud_disclosure_acknowledged?: boolean
}

export interface PreflightResponse {
  warnings: PreflightWarning[]
  blockers: PreflightBlocker[]
  can_proceed: boolean
}

export interface TelemetryPayload {
  weather: string
  /** Integer °F for VTE primary readout; null when unavailable. */
  temperatureF: number | null
  /** Condition or summary text excluding the primary temperature numeral. */
  weatherDetail: string
  /** Parsed micro-climate archetype for per-condition Weather card icons. */
  weatherCondition?: WeatherConditionArchetype | null
  briefing: string
  sports: string
  news: string
  email: string
  calendar: string
  reminders: string
  activeReminders: ActiveReminder[]
  diagnostics?: SystemDiagnostics | null
  confidenceScore: number
  failedConnectors: string[]
  connectorHealth: ConnectorHealthEntry[]
  digest?: DigestPayload
  defaultProfile?: AssistantProfile
  askApexEnabled?: boolean
  tool_outputs?: ToolOutputItem[]
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'

export type MarketTickerStatus = 'live' | 'stale' | 'unavailable'

export type MarketResponseStatus =
  | 'live'
  | 'partial'
  | 'stale'
  | 'unavailable'
  | 'not_configured'
  | 'provider_unavailable'

export interface MarketTickerItem {
  symbol: string
  price: number | null
  change: number | null
  change_percent: number | null
  status: MarketTickerStatus
  last_updated: string | null
  sparkline: number[]
}

export interface MarketResponse {
  status: MarketResponseStatus
  cooldown_active: boolean
  cooldown_remaining_seconds: number
  tickers: MarketTickerItem[]
}

export interface ApexDataState {
  data: TelemetryPayload | null
  status: SystemState
  error: string | null
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
  isSpeaking: boolean
  activeReminders: ActiveReminder[]
  demoModeActive: boolean
  devModeActive: boolean
  confidenceScore: number
  failedConnectors: string[]
  connectorHealth: ConnectorHealthEntry[]
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
  defaultProfile?: AssistantProfile
  askApexEnabled?: boolean
  marketEnabled: boolean
  synthesisStrategy: SynthesisStrategy
  synthesisProvider: SynthesisProvider | null
  synthesisProfile: SynthesisProfile | null
  synthesisFallbackReason: string | null
}
