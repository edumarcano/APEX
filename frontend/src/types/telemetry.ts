export type TtsEngine = 'google' | 'kokoro' | 'pyttsx3'
export type LocalReasoningMode = 'none' | 'focused'

export interface PipelineState {
  step: number
  label: string
  timestamp: string
  is_speaking: boolean
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
  synthesis?: SynthesisLiveState | null
}

export type SynthesisProvider = 'gemini' | 'ollama' | 'openai' | 'xai' | 'raw' | 'demo'
export type SynthesisAgent = 'panthera' | 'mus' | 'sorex'
export type SynthesisStrategy = 'cloud' | 'local' | 'raw' | 'demo'

export interface SynthesisLiveState {
  phase: 'idle' | 'loading' | 'ready' | 'generating' | 'fallback' | 'complete'
  provider: SynthesisProvider | null
  agent: SynthesisAgent | null
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
  role: 'user' | 'agent' | 'tool'
  content?: string
  tool_outputs?: ToolOutputItem[]
}

export type WeatherConditionArchetype =
  | 'clear_day'
  | 'clear_night'
  | 'clouds'
  | 'rain'
  | 'thunderstorm'

export type AgentRuntime = 'cloud' | 'local'
export type CloudEffort = 'light' | 'focused' | 'extended'
export type CloudSettingsAgent = 'panthera' | 'neofelis' | 'delphinus' | 'orcinus'
export type LocalSettingsAgent = 'sorex' | 'mus' | 'apodemus' | 'neotoma'

export type CloudAgent = CloudSettingsAgent

export type AgentKey =
  | CloudSettingsAgent
  | LocalSettingsAgent
  | 'acinonyx'

export type ToolCatalogGroupKind = 'apex_family' | 'mcp_server'

export interface ToolCatalogTool {
  name: string
  label: string
  description: string
  origin: 'native' | 'mcp'
  source_id: string
  apex_family: string | null
  risk: 'read' | 'write' | 'destructive'
  available: boolean
  unavailable_reason: string | null
  estimated_schema_tokens: number
  allowed_for_agent: boolean
}

export interface ToolCatalogGroup {
  id: string
  label: string
  kind: ToolCatalogGroupKind
  tool_count: number
  schema_token_subtotal: number
  tools: ToolCatalogTool[]
}

export interface ToolProfileMetadata {
  id: string
  name: string
  description: string
  tool_names: string[]
  built_in: boolean
  dynamic: boolean
}

export interface ToolCatalog {
  agent: AgentKey
  groups: ToolCatalogGroup[]
  tools: ToolCatalogTool[]
  profiles: ToolProfileMetadata[]
  default_profile_id: string
  default_profile_name: string
  default_selected_tool_names: string[]
  provider_hosted_tools: string[]
  context_window: number | null
  reserved_response_tokens: number | null
}

export interface ToolSelectionFailure {
  name: string
  code: string
  reason: string
}

export interface ToolSelectionDiagnostics {
  requested_tool_names: string[]
  offered_tool_names: string[]
  rejected_tool_names: string[]
  rejected_tools: ToolSelectionFailure[]
  selected_schema_tokens: number
  active_profile_id: string | null
  active_profile_name: string | null
}

export interface ToolTokenBreakdown {
  system_instructions: number
  conversation_history: number
  hud_context: number
  selected_tool_schemas: number
  current_prompt: number
  total: number
  configured_context_window: number | null
  reserved_response_tokens: number | null
  remaining_estimated_capacity: number | null
  is_estimate: boolean
}

export interface ToolPreflightEstimate {
  agent: AgentKey
  selection: ToolSelectionDiagnostics
  breakdown: ToolTokenBreakdown
  warning: string | null
  can_proceed: boolean
}

export interface LocalContextUsage {
  estimated_prompt_tokens: number
  peak_prompt_tokens: number | null
  context_window: number
  history_messages_dropped: number
}

export type AgentAvailabilityStatus =
  | 'available'
  | 'busy'
  | 'configured'
  | 'verifying'
  | 'verified'
  | 'unauthorized'
  | 'model_unavailable'
  | 'rate_limited'
  | 'quota_exhausted'
  | 'billing_blocked'
  | 'provider_unreachable'
  | 'provider_error'
  | 'unknown'
  | 'disabled'
  | 'ollama_unreachable'
  | 'model_not_installed'
  | 'insufficient_ram'
  | 'cpu_overloaded'

export type AgentStability = 'stable' | 'preview'
export type AgentStatusSource = 'configuration' | 'verification' | 'request' | 'runtime'

export interface AgentPricingMetadata {
  currency: 'USD'
  pricing_version: string
  billing_basis: 'free_tier' | 'standard' | 'local'
  input_per_million: number
  output_per_million: number
  cached_input_per_million: number | null
  long_context_threshold_tokens: number | null
  long_context_input_per_million: number | null
  long_context_output_per_million: number | null
  long_context_cached_input_per_million: number | null
}

export interface LocalLoadedModelStatus {
  provider: 'ollama' | 'llama_cpp'
  name: string
  model: string
  state: 'unloaded' | 'loading' | 'loaded' | 'sleeping' | 'failed' | 'unknown'
  context_window: number | null
  size_bytes: number | null
  size_vram_bytes: number | null
  processor: string | null
  context: string | null
  expires_at: string | null
}

/** @deprecated Prefer LocalLoadedModelStatus */
export type LoadedOllamaModelStatus = LocalLoadedModelStatus

export interface AgentStatus {
  key: AgentKey
  description: string
  configured_model: string
  native_tools: Record<string, boolean>
  display_name: string
  provider: 'ollama' | 'llama_cpp' | 'gemini' | 'openai' | 'xai'
  version: string
  sort_order: number
  capabilities: string[]
  runtime: AgentRuntime
  tier: string
  stability: AgentStability
  effort_options: CloudEffort[] | null
  default_effort: CloudEffort | null
  context_window: number | null
  context_window_options: number[] | null
  context_window_high_resource_options: number[] | null
  default_context_window: number | null
  reasoning_mode: LocalReasoningMode | null
  reasoning_mode_options: LocalReasoningMode[] | null
  default_reasoning_mode: LocalReasoningMode | null
  status: AgentAvailabilityStatus
  status_source: AgentStatusSource
  status_checked_at: string | null
  provider_account_tier: string | null
  pricing: AgentPricingMetadata
  active: boolean
  loading: boolean
  reason: string | null
  idle_unload_remaining_seconds: number | null
  loaded_model: LocalLoadedModelStatus | null
}

export interface AgentInitialSelection {
  runtime: AgentRuntime
  agent: AgentKey
  effort: CloudEffort | null
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

export type BriefingMode = 'panthera' | 'mus' | 'sorex' | 'structured_digest'

export type PreflightOperation =
  | 'activate'
  | 'activate_with_briefing'
  | 'refresh_telemetry'
  | 'generate_briefing'
  | 'cortex_query'

export type PreflightWarningCode =
  | 'outside_configured_network'
  | 'network_trust_unknown'
  | 'running_on_battery'
  | 'rapid_connector_refresh'
  | 'high_resource_local_agent'

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
  briefing_mode?: BriefingMode | null
  synthesis_agent?: string | null
  force?: boolean
  involves_cloud?: boolean
  acknowledged_warnings?: string[]
  /** Accepted by older servers; ignored by the current preflight contract. */
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
  defaultAgent?: AgentKey
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
  defaultAgent?: AgentKey
  agentInitialSelection?: AgentInitialSelection
  briefingDefaultMode?: 'panthera' | 'mus' | 'sorex' | 'structured_digest'
  voiceMode?: 'off' | 'manual' | 'automatic'
  askApexEnabled?: boolean
  marketEnabled: boolean
  synthesisStrategy: SynthesisStrategy
  synthesisProvider: SynthesisProvider | null
  synthesisAgent: SynthesisAgent | null
  synthesisFallbackReason: string | null
}
